from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from onyx.tools.tool_implementations.open_url.models import (
    WebContent,
    WebContentProvider,
)
from onyx.tools.tool_implementations.web_search.utils import MAX_CHARS_PER_URL
from onyx.utils.logger import setup_logger
from onyx.utils.url import normalize_url

logger = setup_logger()

SREZAI_READ_URL = "https://srezai.ru/api/v1/read"
# The free tier accepts up to 5 URLs per request (PRO: 10).
SREZAI_READ_MAX_URLS = 5
# Pages are read in a real browser with fallbacks, so one batch can take ~20 s;
# stay under the 2-minute outer timeout of the open_url tool.
_DEFAULT_TIMEOUT_SECONDS = 55
# The service allows 10 requests per 10 s per key: keep parallel batches low.
_MAX_PARALLEL_BATCHES = 2
_MAX_ERROR_DETAIL_CHARS = 200

# Short, LLM-facing explanations for the per-page error codes.
_PAGE_FAILURE_REASONS = {
    "read_failed": "the site returned no readable text (stub page, login wall or file)",
    "source_refused": "the site did not respond to the reader",
    "upstream_timeout": "the site did not respond in time",
    "host_unresolved": "the domain does not resolve",
    "ssrf_blocked": "only public http/https addresses can be read",
}


class SrezaiReadClient(WebContentProvider):
    """srezai.ru `/api/v1/read`: page text as clean markdown, read in batches."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._timeout_seconds = timeout_seconds
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def contents(self, urls: Sequence[str]) -> list[WebContent]:
        # Each URL is billed once, so duplicates are dropped before the request.
        unique_urls = list(dict.fromkeys(urls))
        if not unique_urls:
            return []

        batches = [
            unique_urls[i : i + SREZAI_READ_MAX_URLS]
            for i in range(0, len(unique_urls), SREZAI_READ_MAX_URLS)
        ]
        with ThreadPoolExecutor(
            max_workers=min(_MAX_PARALLEL_BATCHES, len(batches))
        ) as executor:
            results = list(executor.map(self._read_batch, batches))
        return [content for batch in results for content in batch]

    def _read_batch(self, urls: list[str]) -> list[WebContent]:
        body: dict[str, Any] = {"urls": urls, "maxChars": MAX_CHARS_PER_URL}
        try:
            response = requests.post(
                SREZAI_READ_URL,
                headers=self._headers,
                json=body,
                timeout=self._timeout_seconds,
                # A redirect would resend the key to another host.
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            return self._fail_all(urls, f"srezai.ru read request failed: {exc}")

        if response.status_code != 200:
            return self._fail_all(urls, _build_error_message(response))

        try:
            data = response.json()
        except ValueError:
            return self._fail_all(urls, "srezai.ru read returned a non-JSON response")

        pages = data.get("pages") if isinstance(data, dict) else None
        if not isinstance(pages, list):
            return self._fail_all(
                urls, "srezai.ru read returned an unexpected response shape"
            )

        self._last_error = None
        return _match_pages(urls, pages)

    def _fail_all(self, urls: list[str], reason: str) -> list[WebContent]:
        self._last_error = reason
        logger.warning("srezai.ru read failed for %d url(s): %s", len(urls), reason)
        return [_failed(url, reason) for url in urls]


def _match_pages(urls: list[str], pages: list[Any]) -> list[WebContent]:
    """Pair each requested URL with its page.

    Pages come back in request order, so pair by position when the counts
    match. Otherwise pair by normalized URL: the service can normalize the
    address it read (for example, add a trailing slash).
    """
    page_dicts = [page if isinstance(page, dict) else {} for page in pages]
    if len(page_dicts) == len(urls):
        return [
            _to_web_content(url, page)
            for url, page in zip(urls, page_dicts, strict=True)
        ]

    by_url = {
        _match_key(page.get("url")): page
        for page in page_dicts
        if isinstance(page.get("url"), str)
    }
    return [
        (
            _to_web_content(url, by_url[_match_key(url)])
            if _match_key(url) in by_url
            else _failed(url, "srezai.ru returned no page for this URL")
        )
        for url in urls
    ]


def _to_web_content(url: str, page: dict[str, Any]) -> WebContent:
    if page.get("code") or page.get("error"):
        code = page.get("code")
        detail = page.get("error")
        reason = _PAGE_FAILURE_REASONS.get(code) if isinstance(code, str) else None
        return _failed(
            url,
            reason
            or (detail[:_MAX_ERROR_DETAIL_CHARS] if isinstance(detail, str) else None)
            or "srezai.ru could not read the page",
        )

    markdown = page.get("markdown")
    text = markdown.strip() if isinstance(markdown, str) else ""
    if not text:
        return _failed(url, "the page has no readable text")

    title = page.get("title")
    return WebContent(
        title=title.strip() if isinstance(title, str) else "",
        link=url,
        full_content=text,
        published_date=None,
        scrape_successful=True,
    )


def _failed(url: str, reason: str) -> WebContent:
    return WebContent(
        title="",
        link=url,
        full_content="",
        published_date=None,
        scrape_successful=False,
        failure_reason=reason,
    )


def _match_key(url: Any) -> str:
    return normalize_url(url).rstrip("/").lower() if isinstance(url, str) else ""


def _build_error_message(response: requests.Response) -> str:
    try:
        payload: Any = response.json()
    except Exception:
        payload = None

    if response.status_code == 401:
        return "srezai.ru rejected the API key (status 401)"
    if isinstance(payload, dict):
        code = payload.get("code")
        if code == "insufficient_funds":
            return "the srezai.ru account has no credits left"
        detail = payload.get("error")
        if isinstance(detail, str):
            return (
                f"srezai.ru read failed (status {response.status_code}): "
                f"{detail[:_MAX_ERROR_DETAIL_CHARS]}"
            )
    return f"srezai.ru read failed (status {response.status_code})"
