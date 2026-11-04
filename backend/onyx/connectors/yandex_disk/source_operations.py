"""Yandex Disk source-operations gateway: every Disk API call lives here.

The gateway owns the credential: a manual token is sent as is, an OAuth token
is refreshed under the provider's rotation lock and written back, since Yandex
rotates the refresh token on every refresh. It keeps under the request rate
the API terms allow, waits out rate limits and maintenance, and turns every
other refusal into a typed error. Indexing, pruning and the capability checks
all go through the operations below and nothing else talks to
cloud-api.yandex.net or oauth.yandex.ru.
"""

import time
from contextlib import ExitStack
from typing import Any
from urllib.parse import urlsplit

import requests

from onyx.configs.app_configs import YANDEX_DISK_CLIENT_ID, YANDEX_DISK_CLIENT_SECRET
from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.cross_connector_utils.download import download_file as fetch_url
from onyx.connectors.exceptions import SourceApiError
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.connectors.yandex_disk.models import (
    YandexDiskFolder,
    YandexDiskInfo,
    YandexDiskResource,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_after import parse_retry_after_seconds

logger = setup_logger()

# A manual token has only the access token; an OAuth sign-in adds the other two.
ACCESS_TOKEN: str = "yandex_disk_access_token"
REFRESH_TOKEN: str = "yandex_disk_refresh_token"
EXPIRES_AT: str = "yandex_disk_expires_at"
OAUTH_AUTHORIZE_URL: str = "https://oauth.yandex.ru/authorize"
_TOKEN_URL: str = "https://oauth.yandex.ru/token"
# An access token this close to expiry is refreshed before use.
_REFRESH_BUFFER_SECONDS: int = 300
# Three attempts of at most 70 seconds each stay well inside the provider's
# 900-second lock.
_REFRESH_ATTEMPTS: int = 3
_REFRESH_RETRY_STATUSES: frozenset[int] = frozenset({500, 502, 503, 504})
API_URL: str = "https://cloud-api.yandex.net/v1/disk"
_RESOURCES_URL: str = f"{API_URL}/resources"
_DOWNLOAD_LINK_URL: str = f"{API_URL}/resources/download"
# A connection or TLS handshake that hangs fails fast and is retried; an
# answer may take longer.
_CONNECT_TIMEOUT_SECONDS: float = 10
_READ_TIMEOUT_SECONDS: float = 60
_NUM_ATTEMPTS: int = 5
# Each download attempt asks for a new link, so a bad link is not reused.
_DOWNLOAD_ATTEMPTS: int = 3
_MAX_WAIT_SECONDS: float = 60
# The API terms allow up to 40 requests a second per application; one
# gateway keeps to 10.
_MIN_REQUEST_INTERVAL_SECONDS: float = 0.1
# A wait can pass a rate limit (429), maintenance (423) or a server fault.
_RETRY_STATUSES: frozenset[int] = frozenset({423, 429, 500, 502, 503, 504})
_UNAUTHORIZED: int = 401
_FORBIDDEN: int = 403
_NOT_FOUND: int = 404
_RATE_LIMITED: int = 429
# Download links point to downloader.disk.yandex.ru, which can redirect to
# *.storage.yandex.net.
_DOWNLOAD_HOST_SUFFIXES: tuple[str, ...] = (".yandex.ru", ".yandex.net")
_RESOURCE_FIELDS: tuple[str, ...] = (
    "name",
    "path",
    "type",
    "resource_id",
    "created",
    "modified",
    "size",
    "mime_type",
)
_FOLDER_FIELDS: str = ",".join(
    [
        "type",
        "path",
        "_embedded.total",
        *(f"_embedded.items.{field}" for field in _RESOURCE_FIELDS),
    ]
)
_DISK_FIELDS: str = "user.login,user.display_name"
# Names are unique in a folder, so this order is the same on every page.
_FOLDER_SORT: str = "name"


class YandexDiskApiError(SourceApiError, RuntimeError):
    """The Disk API answered a request with an error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None,
        url: str,
        body: str | None,
        method: str = "GET",
    ) -> None:
        super().__init__(
            message, status_code=status_code, method=method, url=url, body=body
        )


class YandexDiskAuthError(YandexDiskApiError):
    """The Disk API refused the token: revoked, expired or malformed."""


class YandexDiskForbiddenError(YandexDiskApiError):
    """The token works but may not read this resource."""


class YandexDiskNotFoundError(YandexDiskApiError):
    """The path does not exist on the Disk."""


class YandexDiskRateLimitError(YandexDiskApiError):
    """The rate limit still refused the request after the waits."""


class YandexDiskUnavailableError(YandexDiskApiError):
    """Maintenance or a server fault outlasted the waits."""


class YandexDiskDownloadError(YandexDiskApiError):
    """The download server refused one file's body, after the retries for a
    fault. The API itself answered, so the file is skipped and the run goes on."""


class YandexDiskTokenRefreshError(YandexDiskApiError):
    """Yandex OAuth refused to issue or renew a token, or the OAuth app is not
    configured on this server."""


class YandexDiskTokenLockError(RuntimeError):
    """Another task holds the lock that renews the OAuth token."""


class YandexDiskUnreachableError(RuntimeError):
    """No answer from the Disk API after retries."""

    def __init__(self, message: str, *, timed_out: bool) -> None:
        super().__init__(message)
        self.timed_out = timed_out


class YandexDiskUnexpectedLinkError(RuntimeError):
    """The API returned a download link off the Yandex hosts."""


def _unreachable(error: requests.RequestException) -> YandexDiskUnreachableError:
    # A connect timeout is also a ConnectionError: it counts as a timeout.
    return YandexDiskUnreachableError(
        f"Yandex Disk did not answer: {error}",
        timed_out=isinstance(error, requests.Timeout),
    )


def _error_response(status_code: int, text: str, url: str) -> YandexDiskApiError:
    if status_code == _UNAUTHORIZED:
        return YandexDiskAuthError(
            f"Yandex Disk refused the token: {text}",
            status_code=status_code,
            url=url,
            body=text,
        )
    if status_code == _FORBIDDEN:
        return YandexDiskForbiddenError(
            f"Yandex Disk denied access: {text}",
            status_code=status_code,
            url=url,
            body=text,
        )
    if status_code == _NOT_FOUND:
        return YandexDiskNotFoundError(
            f"Not found on Yandex Disk: {text}",
            status_code=status_code,
            url=url,
            body=text,
        )
    if status_code == _RATE_LIMITED:
        return YandexDiskRateLimitError(
            f"Yandex Disk rate limited the request: {text}",
            status_code=status_code,
            url=url,
            body=text,
        )
    if status_code in _RETRY_STATUSES:
        return YandexDiskUnavailableError(
            f"Yandex Disk is unavailable: {text}",
            status_code=status_code,
            url=url,
            body=text,
        )
    return YandexDiskApiError(
        f"Error querying Yandex Disk: {text}",
        status_code=status_code,
        url=url,
        body=text,
    )


def _backoff_seconds(attempt: int) -> float:
    return min(float(2**attempt), _MAX_WAIT_SECONDS)


def _wait_seconds(response: requests.Response, attempt: int) -> float:
    told: float | None = parse_retry_after_seconds(response.headers.get("Retry-After"))
    if told is None:
        return _backoff_seconds(attempt)
    return min(told, _MAX_WAIT_SECONDS)


def _is_yandex_download_link(href: str) -> bool:
    parts = urlsplit(href)
    host: str = (parts.hostname or "").lower()
    return parts.scheme == "https" and host.endswith(_DOWNLOAD_HOST_SUFFIXES)


def _without_query(href: str) -> str:
    """The link without its signed query, for error messages and logs."""
    return urlsplit(href)._replace(query="", fragment="").geturl()


def _oauth_app() -> tuple[str, str]:
    """The id and secret of Yahont's Yandex OAuth app, set in the cloud."""
    if not YANDEX_DISK_CLIENT_ID or not YANDEX_DISK_CLIENT_SECRET:
        raise YandexDiskTokenRefreshError(
            "The Yandex OAuth app is not configured on this server.",
            status_code=None,
            url=_TOKEN_URL,
            body=None,
            method="POST",
        )
    return YANDEX_DISK_CLIENT_ID, YANDEX_DISK_CLIENT_SECRET


def _token_error(response: requests.Response) -> YandexDiskTokenRefreshError:
    try:
        body: Any = response.json()
    except ValueError:
        body = None
    fields: dict[str, Any] = body if isinstance(body, dict) else {}
    reason: str = " ".join(
        str(fields[key]) for key in ("error", "error_description") if fields.get(key)
    )
    return YandexDiskTokenRefreshError(
        f"Yandex OAuth refused the request: {reason or response.status_code}",
        status_code=response.status_code,
        url=_TOKEN_URL,
        body=response.text,
        method="POST",
    )


def _token_answer(response: requests.Response) -> dict[str, Any]:
    try:
        body: Any = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or not body.get("access_token"):
        raise YandexDiskTokenRefreshError(
            "Yandex OAuth answered without a token.",
            status_code=response.status_code,
            url=_TOKEN_URL,
            body=None,
            method="POST",
        )
    return body


def _post_token(data: dict[str, str], *, retry: bool) -> dict[str, Any]:
    """The token endpoint's answer. With ``retry``, a network failure and a
    server fault are retried. A retry cannot lose a rotated refresh token: an
    answer lost to a timeout is lost with or without it."""
    attempts: int = _REFRESH_ATTEMPTS if retry else 1
    for attempt in range(attempts):
        last: bool = attempt == attempts - 1
        try:
            response = requests.post(
                _TOKEN_URL,
                data=data,
                timeout=(_CONNECT_TIMEOUT_SECONDS, _READ_TIMEOUT_SECONDS),
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            if last:
                raise _unreachable(e) from e
            logger.warning("Yandex OAuth did not answer: %s. Retrying...", e)
            time.sleep(_backoff_seconds(attempt))
            continue
        if response.ok:
            return _token_answer(response)
        if response.status_code in _REFRESH_RETRY_STATUSES and not last:
            time.sleep(_backoff_seconds(attempt))
            continue
        raise _token_error(response)
    raise RuntimeError("Unexpected execution when querying Yandex OAuth.")


def _credentials_from(
    token_data: dict[str, Any], stored: dict[str, Any]
) -> dict[str, Any]:
    """The stored credential with the answer's tokens. Per RFC 6749 section 6
    the answer may omit the refresh token, which leaves the stored one valid."""
    credentials: dict[str, Any] = {**stored, ACCESS_TOKEN: token_data["access_token"]}
    refresh_token: Any = token_data.get("refresh_token", stored.get(REFRESH_TOKEN))
    if refresh_token:
        credentials[REFRESH_TOKEN] = refresh_token
    if "expires_in" in token_data:
        credentials[EXPIRES_AT] = int(time.time() + int(token_data["expires_in"]))
    return credentials


def exchange_code_for_token(code: str) -> dict[str, Any]:
    """The credential a sign-in code buys. A code works once, so there is no
    retry."""
    client_id, client_secret = _oauth_app()
    return _credentials_from(
        _post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            retry=False,
        ),
        {},
    )


def refresh_oauth_token(credentials: dict[str, Any]) -> dict[str, Any]:
    """The credential after one refresh. Yandex rotates the refresh token, so
    the caller must write the result back before anything else refreshes."""
    refresh_token: Any = credentials.get(REFRESH_TOKEN)
    if not refresh_token:
        raise ConnectorMissingCredentialError("Yandex Disk")
    client_id, client_secret = _oauth_app()
    return _credentials_from(
        _post_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": str(refresh_token),
                "client_id": client_id,
                "client_secret": client_secret,
            },
            retry=True,
        ),
        credentials,
    )


def is_expiring(credentials: dict[str, Any]) -> bool:
    """An OAuth credential that must be refreshed before its next use. A
    manual token, or one with nothing to refresh it, never is."""
    return (
        ACCESS_TOKEN in credentials
        and REFRESH_TOKEN in credentials
        and EXPIRES_AT in credentials
        and credentials[EXPIRES_AT] < time.time() + _REFRESH_BUFFER_SECONDS
    )


class YandexDiskSourceOperations(SourceOperations):
    source = DocumentSource.YANDEX_DISK
    sdk_modules = ("requests",)
    config_keys = frozenset()

    _authorization_cache: str | None = None
    _authorization_expires_at: float | None = None
    _last_request_at: float = 0.0

    def _authorization(self) -> str:
        """The Authorization header value, refreshing an expiring OAuth token
        under the provider's lock so two tasks never both redeem it."""
        now: float = time.time()
        if self._authorization_cache is not None and (
            self._authorization_expires_at is None
            or self._authorization_expires_at >= now + _REFRESH_BUFFER_SECONDS
        ):
            return self._authorization_cache
        credentials: dict[str, Any] = self.credentials_provider.get_credentials()
        if is_expiring(credentials):
            with self._refresh_lock():
                credentials = self.credentials_provider.get_credentials()
                if is_expiring(credentials):
                    credentials = refresh_oauth_token(credentials)
                    self.credentials_provider.set_credentials(credentials)
        token: Any = credentials.get(ACCESS_TOKEN)
        if not token:
            raise ConnectorMissingCredentialError("Yandex Disk")
        self._authorization_cache = f"OAuth {token}"
        self._authorization_expires_at = (
            credentials.get(EXPIRES_AT) if REFRESH_TOKEN in credentials else None
        )
        return self._authorization_cache

    def _refresh_lock(self) -> ExitStack:
        """The provider's rotation lock, held by the returned stack. Only
        taking the lock is wrapped, so a failed refresh keeps its own error."""
        stack = ExitStack()
        try:
            stack.enter_context(self.credentials_provider)
        except RuntimeError as e:
            raise YandexDiskTokenLockError(
                "Another task holds the lock that renews the Yandex OAuth token."
            ) from e
        return stack

    def _throttle(self) -> None:
        wait: float = (
            self._last_request_at + _MIN_REQUEST_INTERVAL_SECONDS - time.monotonic()
        )
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        headers: dict[str, str] = {"Authorization": self._authorization()}
        for attempt in range(_NUM_ATTEMPTS):
            self._throttle()
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=(_CONNECT_TIMEOUT_SECONDS, _READ_TIMEOUT_SECONDS),
                )
            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt == _NUM_ATTEMPTS - 1:
                    raise _unreachable(e) from e
                logger.warning("Yandex Disk did not answer: %s. Retrying...", e)
                time.sleep(_backoff_seconds(attempt))
                continue
            if response.ok:
                body: dict[str, Any] = response.json()
                return body
            error: YandexDiskApiError = _error_response(
                response.status_code, response.text, url
            )
            if (
                response.status_code not in _RETRY_STATUSES
                or attempt == _NUM_ATTEMPTS - 1
            ):
                raise error
            wait: float = _wait_seconds(response, attempt)
            logger.warning(
                "Yandex Disk answered %s. Retrying in %s s.",
                response.status_code,
                wait,
            )
            time.sleep(wait)
        raise RuntimeError("Unexpected execution when querying Yandex Disk.")

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_disk_info(self) -> YandexDiskInfo:
        data: dict[str, Any] = self._get(API_URL, {"fields": _DISK_FIELDS})
        user: dict[str, Any] = data.get("user") or {}
        return YandexDiskInfo(
            login=user.get("login"), display_name=user.get("display_name")
        )

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.CONFIG,
    )
    def list_folder(self, *, path: str, offset: int, limit: int) -> YandexDiskFolder:
        """One page of the folder at ``path``, folders first."""
        data: dict[str, Any] = self._get(
            _RESOURCES_URL,
            {
                "path": path,
                "offset": offset,
                "limit": limit,
                "sort": _FOLDER_SORT,
                "fields": _FOLDER_FIELDS,
            },
        )
        embedded: dict[str, Any] = data.get("_embedded") or {}
        return YandexDiskFolder(
            path=data.get("path") or path,
            type=data["type"],
            items=[
                YandexDiskResource.model_validate(item)
                for item in embedded.get("items") or []
            ],
            total=embedded.get("total"),
        )

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.CONFIG,
        untested=(
            "Transfers a file body; the checks read metadata only and never "
            "download file contents."
        ),
    )
    def download_file(self, *, path: str, max_size_bytes: int) -> bytes | None:
        """The file at ``path``, or None when its body runs past
        ``max_size_bytes``. A download server fault or a dead connection is
        retried with a new link; a refusal of the body that outlasts the
        retries is a ``YandexDiskDownloadError``."""
        for attempt in range(_DOWNLOAD_ATTEMPTS):
            last: bool = attempt == _DOWNLOAD_ATTEMPTS - 1
            href: str = self._download_link(path)
            self._throttle()
            try:
                return fetch_url(
                    href,
                    max_size_bytes=max_size_bytes,
                    timeout_seconds=_READ_TIMEOUT_SECONDS,
                    headers={"Authorization": self._authorization()},
                )
            except requests.HTTPError as e:
                if e.response is None:
                    raise
                status_code: int = e.response.status_code
                if status_code == _NOT_FOUND:
                    raise _error_response(
                        status_code, e.response.text, _without_query(href)
                    ) from e
                if status_code in _RETRY_STATUSES and not last:
                    logger.warning(
                        "Yandex Disk download of %s answered %s. Retrying...",
                        path,
                        status_code,
                    )
                    time.sleep(_wait_seconds(e.response, attempt))
                    continue
                raise YandexDiskDownloadError(
                    f"The Yandex Disk download server answered {status_code} "
                    f"for {path}.",
                    status_code=status_code,
                    url=_without_query(href),
                    body=e.response.text,
                ) from e
            except (requests.ConnectionError, requests.Timeout) as e:
                if last:
                    raise _unreachable(e) from e
                logger.warning(
                    "Yandex Disk download of %s failed: %s. Retrying...", path, e
                )
                time.sleep(_backoff_seconds(attempt))
        raise RuntimeError("Unexpected execution when downloading from Yandex Disk.")

    def _download_link(self, path: str) -> str:
        link: dict[str, Any] = self._get(
            _DOWNLOAD_LINK_URL, {"path": path, "fields": "href"}
        )
        href: str = str(link.get("href") or "")
        if not _is_yandex_download_link(href):
            raise YandexDiskUnexpectedLinkError(
                f"Yandex Disk returned a download link off its hosts: "
                f"{_without_query(href)}"
            )
        return href
