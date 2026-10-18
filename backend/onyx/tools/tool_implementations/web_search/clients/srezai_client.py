from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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

SREZAI_SEARCH_URL = "https://srezai.ru/api/v1/search"
SREZAI_MAX_RESULTS = 30
# Russian-speaking users write queries in Russian and in English: let the
# service detect the language, and query the general-purpose engine set.
_DEFAULT_LANGUAGE = "auto"
_DEFAULT_CATEGORY = "general"
_DEFAULT_TIMEOUT_SECONDS = 30
_MAX_ERROR_DETAIL_CHARS = 200
# Error codes the service marks as "a retry helps".
_RETRYABLE_CODES = {
    "rate_limited",
    "service_unavailable",
    "search_unavailable",
    "upstream_timeout",
}


class RetryableSrezaiSearchError(Exception):
    """Error type used to trigger retry for transient srezai.ru failures."""


class SrezaiSearchClient(WebSearchProvider):
    """srezai.ru `/api/v1/search`; page reading lives in `open_url.srezai`.

    The service honors the `site:` operator in the query (checked against the
    live API), so `supports_site_filter` stays True.
    """

    def __init__(
        self,
        api_key: str,
        *,
        num_results: int = 10,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._num_results = max(1, min(num_results, SREZAI_MAX_RESULTS))
        self._timeout_seconds = timeout_seconds

    def _build_request_body(self, query: str) -> dict[str, Any]:
        return {
            "query": query,
            "num": self._num_results,
            "language": _DEFAULT_LANGUAGE,
            "category": _DEFAULT_CATEGORY,
        }

    @retry_builder(
        tries=3,
        delay=1,
        backoff=2,
        exceptions=(RetryableSrezaiSearchError,),
    )
    def _search_with_retries(self, query: str) -> list[WebSearchResult]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                SREZAI_SEARCH_URL,
                headers=headers,
                json=self._build_request_body(query),
                timeout=self._timeout_seconds,
                # A redirect would resend the key to another host.
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise RetryableSrezaiSearchError(
                f"srezai.ru search request failed: {exc}"
            ) from exc

        if response.status_code != 200:
            error_msg, code = _build_error_message(response)
            if _is_retryable(response.status_code, code):
                raise RetryableSrezaiSearchError(error_msg)
            raise ValueError(error_msg)

        try:
            data = response.json()
        except ValueError as exc:
            raise RetryableSrezaiSearchError(
                "srezai.ru search returned a non-JSON response."
            ) from exc

        return _parse_results(data)

    def search(self, query: str) -> list[WebSearchResult]:
        try:
            return self._search_with_retries(query)
        except RetryableSrezaiSearchError as exc:
            raise ValueError(str(exc)) from exc

    def test_connection(self) -> dict[str, str]:
        try:
            test_results = self.search("test")
        except ValueError as e:
            error_msg = str(e)
            if "status 401" in error_msg or "unauthorized" in error_msg:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"Invalid srezai.ru API key: {error_msg}",
                ) from e
            if "insufficient_funds" in error_msg:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"The srezai.ru account has no credits left: {error_msg}",
                ) from e
            if "status 429" in error_msg:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"srezai.ru rate limit exceeded: {error_msg}",
                ) from e
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"srezai.ru API key validation failed: {error_msg}",
            ) from e

        if not test_results:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "srezai.ru API key validation failed: search returned no results.",
            )

        logger.info("Web search provider test succeeded for srezai.ru.")
        return {"status": "ok"}


def _parse_results(data: Any) -> list[WebSearchResult]:
    raw_results = data.get("results") if isinstance(data, dict) else None
    if raw_results is None:
        raw_results = []
    if not isinstance(raw_results, list):
        raise ValueError(
            "srezai.ru search returned an unexpected response shape: "
            f"'results' is {type(raw_results).__name__}, expected a list."
        )

    results: list[WebSearchResult] = []
    for result in raw_results:
        if not isinstance(result, dict):
            continue
        link = _clean_string(result.get("url"))
        if not link or _is_irrelevant(result):
            continue
        results.append(
            WebSearchResult(
                title=_clean_string(result.get("title")),
                link=link,
                snippet=_clean_string(result.get("content")),
                author=None,
                published_date=_parse_date(result.get("publishedDate")),
            )
        )
    return results


def _is_irrelevant(result: dict[str, Any]) -> bool:
    """Both relevance signals are zero: an engine's off-topic filler.

    Checked live: a Russian query returned an English "Dentist" page with
    `relevance` 0 and `semantic` ~0. A zero `relevance` alone is kept, because
    `semantic` is None when the reranker did not run.
    """
    relevance = result.get("relevance")
    semantic = result.get("semantic")
    if not isinstance(relevance, (int, float)) or not isinstance(
        semantic, (int, float)
    ):
        return False
    return relevance <= 0 and semantic < 0.01


def _parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _build_error_message(response: requests.Response) -> tuple[str, str | None]:
    detail, code = _extract_error_detail(response)
    code_part = f" [{code}]" if code else ""
    return (
        f"srezai.ru search failed (status {response.status_code}){code_part}: {detail}",
        code,
    )


def _extract_error_detail(response: requests.Response) -> tuple[str, str | None]:
    try:
        payload: Any = response.json()
    except Exception:
        text = response.text.strip()
        return (text[:_MAX_ERROR_DETAIL_CHARS] if text else "No error details"), None

    if isinstance(payload, dict):
        code = payload.get("code")
        detail = payload.get("error")
        return (
            (
                detail[:_MAX_ERROR_DETAIL_CHARS]
                if isinstance(detail, str)
                else str(payload)[:_MAX_ERROR_DETAIL_CHARS]
            ),
            code if isinstance(code, str) else None,
        )

    return str(payload)[:_MAX_ERROR_DETAIL_CHARS], None


def _is_retryable(status_code: int, code: str | None) -> bool:
    if code is not None:
        return code in _RETRYABLE_CODES
    return status_code == 429 or status_code >= 500


def _clean_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
