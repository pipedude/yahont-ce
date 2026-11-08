"""Named indexing checks for Yandex Disk, composed from the gateway's operations.

Indexing needs a token the Disk API accepts and a root folder that exists and
is a folder. ``validate_connector_settings`` runs the same helpers, so the
blocking validation and the check rows agree.
"""

from collections.abc import Callable
from typing import Any, NoReturn, TypeVar

from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckOutput,
    CredentialCapability,
    form_config,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InconclusiveValidationError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
    UnexpectedValidationError,
    UnreachableValidationError,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.yandex_disk.config import (
    YandexDiskConnectorConfig,
    normalize_root_path,
    root_api_path,
)
from onyx.connectors.yandex_disk.models import DIR_TYPE, YandexDiskInfo
from onyx.connectors.yandex_disk.source_operations import (
    REFRESH_TOKEN,
    YandexDiskApiError,
    YandexDiskAuthError,
    YandexDiskForbiddenError,
    YandexDiskNotFoundError,
    YandexDiskRateLimitError,
    YandexDiskSourceOperations,
    YandexDiskTokenLockError,
    YandexDiskTokenRefreshError,
    YandexDiskUnavailableError,
    YandexDiskUnreachableError,
)

T = TypeVar("T")

TOKEN_CHECK_ID: str = "yandex_disk_token"
FOLDER_CHECK_ID: str = "yandex_disk_folder"
_MAX_SUMMARY_CHARS: int = 40
_NEW_TOKEN_LINE: str = (
    "Issue a new OAuth token for the Yandex app, then paste it in the account."
)
_RECONNECT_LINE: str = "Reconnect the account through Yandex."
# A refused renewal: the refresh token is spent, revoked or expired.
_REFRESH_REFUSED_STATUSES: frozenset[int] = frozenset({400, 401})


def is_oauth_credential(credential_json: dict[str, Any]) -> bool:
    """A sign-in through Yandex holds a refresh token; a pasted token does not."""
    return REFRESH_TOKEN in credential_json


def _new_credential_line(oauth: bool) -> str:
    return _RECONNECT_LINE if oauth else _NEW_TOKEN_LINE


def missing_folder_error(root_path: str) -> ConnectorValidationError:
    return ConnectorValidationError(
        f"The folder /{root_path} does not exist on the Yandex Disk.",
        summary="Folder not found",
        description=(
            "No folder has this path on the Disk of the connected account.\n"
            "Check the path, or leave it empty to index the whole Disk."
        ),
    )


def file_root_error(root_path: str) -> ConnectorValidationError:
    return ConnectorValidationError(
        f"/{root_path} is a file, not a folder.",
        summary="Path is a file",
        description="The root folder path names a file.\nEnter the path of a folder.",
    )


def _raise_for_yandex_disk_error(
    error: Exception, failed: str, oauth: bool
) -> NoReturn:
    """Maps a gateway error onto the validation-exception family. ``failed``
    leads the message of an error the check cannot word better; ``oauth`` tells
    whether the credential is a sign-in through Yandex, which is reconnected,
    or a pasted token, which is replaced."""
    if isinstance(error, YandexDiskRateLimitError):
        raise RateLimitedValidationError(
            "The Yandex Disk rate limit stopped the check. Run the checks again later.",
            summary="Rate limited by Yandex Disk",
            description=(
                "The Yandex Disk rate limit stopped the check before it could "
                "decide.\nWait a minute, then re-run."
            ),
        ) from error
    if (
        isinstance(error, YandexDiskTokenRefreshError)
        and error.status_code in _REFRESH_REFUSED_STATUSES
    ):
        raise CredentialExpiredError(
            f"Yandex refused to renew the OAuth token. Reconnect the account. {error}",
            summary="Yandex sign-in expired",
            description=(
                "The OAuth token expired and Yandex refused to renew it.\n"
                f"{_RECONNECT_LINE}"
            ),
        ) from error
    if isinstance(error, (YandexDiskAuthError, ConnectorMissingCredentialError)):
        raise CredentialInvalidError(
            f"Yandex Disk rejected the token: it expired, was revoked or is missing. {error}",
            summary="Yandex Disk rejected the token",
            description=(
                "The token expired, was revoked or is missing.\n"
                f"{_new_credential_line(oauth)}"
            ),
        ) from error
    if isinstance(error, YandexDiskTokenLockError):
        raise InconclusiveValidationError(
            f"{failed} {error}",
            summary="Token refresh is busy elsewhere",
            description=(
                "Another task holds the lock that renews this OAuth token.\n"
                "Wait a few minutes, then re-run."
            ),
        ) from error
    if isinstance(error, YandexDiskForbiddenError):
        raise InsufficientPermissionsError(
            f"Yandex Disk denied the token access to the Disk. {error}",
            summary="Access denied",
            description=(
                "The token may not read the Disk.\nGive the Yandex app the "
                '"Read all of Disk" permission (cloud_api:disk.read), then issue '
                "a new token."
            ),
        ) from error
    if isinstance(error, YandexDiskUnavailableError):
        raise UnreachableValidationError(
            f"Yandex Disk is unavailable: {error}",
            summary="Yandex Disk is unavailable",
            description=(
                "Yandex Disk answered with maintenance or a server fault.\n"
                "Re-run the checks later."
            ),
        ) from error
    if isinstance(error, YandexDiskUnreachableError) and error.timed_out:
        raise UnreachableValidationError(
            f"Yandex Disk did not answer in time: {error}",
            summary="Timed out",
            description=(
                "Yandex Disk did not answer in time.\nRe-run, or check that "
                "cloud-api.yandex.net is reachable."
            ),
        ) from error
    if isinstance(error, YandexDiskUnreachableError):
        raise UnreachableValidationError(
            f"Cannot connect to Yandex Disk: {error}",
            summary="Cannot reach Yandex Disk",
            description=(
                "The request failed before Yandex Disk answered, after retries.\n"
                "Re-run the checks."
            ),
        ) from error
    raise UnexpectedValidationError(
        f"{failed} {error}",
        summary="Unexpected response from Yandex Disk",
        description=(
            "Yandex Disk answered with an error this check does not expect.\n"
            "Re-run the checks. If it repeats, share the error details with support."
        ),
    ) from error


def _probe(action: Callable[[], T], failed: str, oauth: bool) -> T:
    try:
        return action()
    except (
        YandexDiskApiError,
        YandexDiskTokenLockError,
        YandexDiskUnreachableError,
        ConnectorMissingCredentialError,
    ) as error:
        _raise_for_yandex_disk_error(error, failed, oauth)


def check_token(ops: YandexDiskSourceOperations, oauth: bool) -> YandexDiskInfo:
    return _probe(ops.get_disk_info, "Yandex Disk did not accept the token.", oauth)


def check_root_folder(
    ops: YandexDiskSourceOperations, root_path: str, oauth: bool
) -> None:
    """Raises unless the root folder exists and is a folder."""
    root: str = normalize_root_path(root_path)
    try:
        folder = ops.list_folder(path=root_api_path(root), offset=0, limit=1)
    except YandexDiskNotFoundError as e:
        raise missing_folder_error(root) from e
    except (
        YandexDiskApiError,
        YandexDiskTokenLockError,
        YandexDiskUnreachableError,
        ConnectorMissingCredentialError,
    ) as error:
        _raise_for_yandex_disk_error(error, "The root folder could not be read.", oauth)
    if folder.type != DIR_TYPE:
        raise file_root_error(root)


def gateway_from_context(context: CapabilityCheckContext) -> YandexDiskSourceOperations:
    if not isinstance(context.source_operations, YandexDiskSourceOperations):
        raise TypeError(
            "Bug: the runner constructs the registered gateway for migrated sources."
        )
    return context.source_operations


def _fit(line: str, fallback: str) -> str:
    return line if len(line) <= _MAX_SUMMARY_CHARS else fallback


class _YandexDiskCheck(CapabilityCheck[YandexDiskConnectorConfig]):
    def __init__(
        self,
        *,
        check_id: str,
        display_name: str,
        remediation: str,
        requires_connector_config: bool = False,
        validates_binding: bool = False,
        fails_when_unreachable: bool = False,
        depends_on: tuple[str, ...] = (),
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=display_name,
            depends_on=depends_on,
            requires_connector_instance=False,
            requires_connector_config=requires_connector_config,
            remediation=remediation,
            validates_binding=validates_binding,
            fails_when_unreachable=fails_when_unreachable,
        )


class _TokenCheck(_YandexDiskCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=TOKEN_CHECK_ID,
            display_name="Sign in to Yandex Disk",
            remediation=_NEW_TOKEN_LINE,
            validates_binding=True,
            fails_when_unreachable=True,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        info: YandexDiskInfo = check_token(
            gateway_from_context(context), is_oauth_credential(context.credential_json)
        )
        if info.login is None:
            return CheckOutput(summary="Signed in to Yandex Disk")
        return CheckOutput(
            summary=_fit(f"Signed in as {info.login}", "Signed in to Yandex Disk")
        )


class _FolderCheck(_YandexDiskCheck):
    config_class = YandexDiskConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            check_id=FOLDER_CHECK_ID,
            display_name="Find the root folder",
            remediation=(
                "Check the folder path, or leave it empty to index the whole Disk."
            ),
            requires_connector_config=True,
            depends_on=(TOKEN_CHECK_ID,),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        root: str = normalize_root_path(
            form_config(context, YandexDiskConnectorConfig).root_path
        )
        check_root_folder(
            gateway_from_context(context),
            root,
            is_oauth_credential(context.credential_json),
        )
        if not root:
            return CheckOutput(summary="Read the whole Disk")
        return CheckOutput(
            summary=_fit(f"Found folder /{root}", "Found the root folder")
        )


def build_yandex_disk_indexing_checks() -> list[CapabilityCheck]:
    return [_TokenCheck(), _FolderCheck()]
