from __future__ import annotations

import base64
import binascii
import time
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.tools.tool_implementations.web_search.models import (
    WebSearchProvider,
    WebSearchResult,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

YANDEX_SEARCH_URL = "https://searchapi.api.cloud.yandex.net/v2/web/search"
# The API limits: groupsOnPage 1-100, queryText up to 400 characters.
YANDEX_MAX_RESULTS = 100
_MAX_QUERY_CHARS = 400
# Russian search on yandex.ru, ranked for Russia as a whole (region 225).
_SEARCH_TYPE = "SEARCH_TYPE_RU"
_REGION = "225"
_LOCALIZATION = "LOCALIZATION_RU"
_FAMILY_MODE = "FAMILY_MODE_MODERATE"
_FIX_TYPO_MODE = "FIX_TYPO_MODE_ON"
_MAX_PASSAGES = 3
_DEFAULT_TIMEOUT_SECONDS = 30
_MAX_ERROR_DETAIL_CHARS = 200
# The XML error code for "nothing was found": an empty result, not a failure.
_NOTHING_FOUND_CODE = "15"
_DAILY_LIMIT_CODE = "32"


class RetryableYandexSearchError(Exception):
    """Error type used to trigger retry for transient Yandex Search API failures."""


class YandexSearchClient(WebSearchProvider):
    """Yandex Search API `/v2/web/search` (synchronous) with a service account
    API key. Page reading stays with the content provider.

    The API forbids reordering its results, so they keep Yandex's order. The
    service honors the `site:` operator (checked against the live API), so
    `supports_site_filter` stays True.
    """

    def __init__(
        self,
        api_key: str,
        *,
        num_results: int = 20,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._num_results = max(1, min(num_results, YANDEX_MAX_RESULTS))
        self._timeout_seconds = timeout_seconds

    def _build_request_body(self, query: str) -> dict[str, Any]:
        # Proto int64 fields travel as strings in the REST JSON mapping.
        return {
            "query": {
                "searchType": _SEARCH_TYPE,
                "queryText": _cut_query(query),
                "familyMode": _FAMILY_MODE,
                "fixTypoMode": _FIX_TYPO_MODE,
            },
            "groupSpec": {
                "groupMode": "GROUP_MODE_FLAT",
                "groupsOnPage": str(self._num_results),
                "docsInGroup": "1",
            },
            "maxPassages": str(_MAX_PASSAGES),
            "region": _REGION,
            "l10n": _LOCALIZATION,
            "responseFormat": "FORMAT_XML",
        }

    @retry_builder(
        tries=3,
        delay=1,
        backoff=2,
        exceptions=(RetryableYandexSearchError,),
    )
    def _search_with_retries(self, query: str) -> list[WebSearchResult]:
        headers = {
            "Authorization": f"Api-Key {self._api_key}",
            "Content-Type": "application/json",
        }

        started = time.monotonic()
        try:
            response = requests.post(
                YANDEX_SEARCH_URL,
                headers=headers,
                json=self._build_request_body(query),
                timeout=self._timeout_seconds,
                # A redirect would resend the key to another host.
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise RetryableYandexSearchError(
                f"Yandex Search API request failed: {exc}"
            ) from exc

        if response.status_code != 200:
            error_msg = (
                f"Yandex Search API search failed (status {response.status_code}): "
                f"{_error_detail(response)}"
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise RetryableYandexSearchError(error_msg)
            raise ValueError(error_msg)

        try:
            data = response.json()
        except ValueError as exc:
            raise RetryableYandexSearchError(
                "Yandex Search API returned a non-JSON response."
            ) from exc

        results = _parse_results(data)
        # One line per paid request, without the query text.
        logger.info(
            "Yandex Search API search returned %d results in %.2fs",
            len(results),
            time.monotonic() - started,
        )
        return results

    def search(self, query: str) -> list[WebSearchResult]:
        try:
            return self._search_with_retries(query)
        except RetryableYandexSearchError as exc:
            raise ValueError(str(exc)) from exc

    def test_connection(self) -> dict[str, str]:
        try:
            test_results = self.search("Яндекс")
        except ValueError as e:
            error_msg = str(e)
            if "status 401" in error_msg:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"Invalid Yandex Search API key: {error_msg}",
                ) from e
            if "status 403" in error_msg:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "Yandex Search API denied access. Give the service account the "
                    "search-api.webSearch.user role and check that the Yandex Cloud "
                    f"billing account is active: {error_msg}",
                ) from e
            if "status 429" in error_msg:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"Yandex Search API rate limit exceeded: {error_msg}",
                ) from e
            if f"code {_DAILY_LIMIT_CODE}" in error_msg:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"The Yandex Search API request limit is exhausted: {error_msg}",
                ) from e
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Yandex Search API key validation failed: {error_msg}",
            ) from e

        if not test_results:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Yandex Search API key validation failed: search returned no results.",
            )

        logger.info("Web search provider test succeeded for Yandex Search API.")
        return {"status": "ok"}


def _cut_query(query: str) -> str:
    """The query within the API's 400 characters, cut at a word."""
    query = query.strip()
    if len(query) <= _MAX_QUERY_CHARS:
        return query
    cut = query[:_MAX_QUERY_CHARS]
    head, _, _ = cut.rpartition(" ")
    return (head or cut).strip()


def _parse_results(data: Any) -> list[WebSearchResult]:
    raw_data = data.get("rawData") if isinstance(data, dict) else None
    if not isinstance(raw_data, str):
        raise ValueError("Yandex Search API returned no 'rawData' in its answer.")
    try:
        xml = base64.b64decode(raw_data, validate=True)
    except binascii.Error as exc:
        raise ValueError(
            f"Yandex Search API returned an unreadable answer: {exc}"
        ) from exc
    # Yandex never sends a DTD; refusing one rules out entity expansion.
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise ValueError("Yandex Search API returned XML with a DTD; refused.")
    try:
        root = ET.fromstring(xml)  # noqa: S314 - no DTD, see the check above
    except ET.ParseError as exc:
        raise ValueError(
            f"Yandex Search API returned an unreadable answer: {exc}"
        ) from exc

    error = root.find("./response/error")
    if error is not None:
        code = error.get("code")
        if code == _NOTHING_FOUND_CODE:
            return []
        raise ValueError(
            f"Yandex Search API search failed: code {code}: "
            f"{_text(error)[:_MAX_ERROR_DETAIL_CHARS]}"
        )

    results: list[WebSearchResult] = []
    for doc in root.iter("doc"):
        link = _readable_link(_text(doc.find("url")))
        if not link:
            continue
        # `modtime` is not a date of the page: live answers gave 2014-2018 to
        # pages about 2026, and the model reads `published_date` as updated_at.
        results.append(
            WebSearchResult(
                title=_text(doc.find("title")),
                link=link,
                snippet=_snippet(doc),
                author=None,
                published_date=None,
            )
        )
    return results


def _text(element: ET.Element | None) -> str:
    """The element's text with its highlight tags (`<hlword>`) joined in."""
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def _snippet(doc: ET.Element) -> str:
    headline = _text(doc.find("headline"))
    if headline:
        return headline
    return " ".join(
        text for text in (_text(passage) for passage in doc.iter("passage")) if text
    )


def _readable_link(url: str) -> str:
    """The link with a punycode domain (`xn--…`) shown in its own script."""
    parts = urlsplit(url)
    host = parts.hostname
    if not host or "xn--" not in host:
        return url
    try:
        readable = ".".join(
            label.encode("ascii").decode("idna") if label.startswith("xn--") else label
            for label in host.split(".")
        )
    except UnicodeError:
        return url
    return urlunsplit(
        parts._replace(netloc=parts.netloc.lower().replace(host, readable))
    )


def _error_detail(response: requests.Response) -> str:
    try:
        payload: Any = response.json()
    except Exception:
        text = response.text.strip()
        return text[:_MAX_ERROR_DETAIL_CHARS] if text else "No error details"
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        return payload["message"][:_MAX_ERROR_DETAIL_CHARS]
    return str(payload)[:_MAX_ERROR_DETAIL_CHARS]
