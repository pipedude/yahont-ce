from __future__ import annotations

from typing import Any

import pytest
import requests

import onyx.tools.tool_implementations.open_url.srezai as srezai_module
from onyx.tools.tool_implementations.open_url.srezai import (
    SREZAI_READ_URL,
    SrezaiReadClient,
)
from onyx.tools.tool_implementations.web_search.models import WebContentProviderConfig
from onyx.tools.tool_implementations.web_search.providers import (
    build_content_provider_from_config,
)
from onyx.tools.tool_implementations.web_search.utils import MAX_CHARS_PER_URL
from shared_configs.enums import WebContentProviderType


class DummyResponse:
    def __init__(self, *, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("No JSON payload")
        return self._payload


def _page(url: str, markdown: str = "Текст страницы", title: str = "Заголовок") -> dict:
    return {"url": url, "title": title, "markdown": markdown, "engine": "fast"}


def test_contents_reads_pages_in_batches_of_five(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_batches: list[list[str]] = []

    def _mock_post(url: str, **kwargs: Any) -> DummyResponse:
        assert url == SREZAI_READ_URL
        assert kwargs["headers"]["Authorization"] == "Bearer srz_live_test"
        assert kwargs["json"]["maxChars"] == MAX_CHARS_PER_URL
        assert kwargs["allow_redirects"] is False
        batch = kwargs["json"]["urls"]
        sent_batches.append(batch)
        return DummyResponse(
            status_code=200, payload={"pages": [_page(u) for u in batch]}
        )

    monkeypatch.setattr(srezai_module.requests, "post", _mock_post)

    urls = [f"https://example.ru/{i}" for i in range(7)]
    results = SrezaiReadClient(api_key="srz_live_test").contents(
        urls + ["https://example.ru/0"]
    )

    assert sorted(len(b) for b in sent_batches) == [2, 5]
    assert [r.link for r in results] == urls
    assert all(r.scrape_successful for r in results)
    assert results[0].full_content == "Текст страницы"
    assert results[0].title == "Заголовок"


def test_contents_marks_failed_pages_with_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            status_code=200,
            payload={
                "pages": [
                    # The service may normalize the URL it read.
                    _page("https://example.ru/ok/"),
                    {
                        "url": "https://example.ru/stub",
                        "error": "Сайт не отдал текст",
                        "code": "read_failed",
                    },
                    _page("https://example.ru/empty", markdown=""),
                ]
            },
        )

    monkeypatch.setattr(srezai_module.requests, "post", _mock_post)

    results = SrezaiReadClient(api_key="k").contents(
        [
            "https://example.ru/ok",
            "https://example.ru/stub",
            "https://example.ru/empty",
        ]
    )

    assert [r.link for r in results] == [
        "https://example.ru/ok",
        "https://example.ru/stub",
        "https://example.ru/empty",
    ]
    assert results[0].scrape_successful is True
    assert results[1].scrape_successful is False
    assert results[1].failure_reason is not None
    assert "no readable text" in results[1].failure_reason
    assert results[2].scrape_successful is False


def test_contents_maps_pages_by_url_when_counts_differ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            status_code=200,
            payload={"pages": [_page("https://example.ru/b", markdown="B")]},
        )

    monkeypatch.setattr(srezai_module.requests, "post", _mock_post)

    results = SrezaiReadClient(api_key="k").contents(
        ["https://example.ru/a", "https://example.ru/b"]
    )

    assert [(r.link, r.scrape_successful) for r in results] == [
        ("https://example.ru/a", False),
        ("https://example.ru/b", True),
    ]
    assert results[1].full_content == "B"


@pytest.mark.parametrize(
    ("status_code", "payload", "expected"),
    [
        (
            402,
            {"error": "Недостаточно кредитов", "code": "insufficient_funds"},
            "no credits left",
        ),
        (401, {"error": "Нужен ключ", "code": "unauthorized"}, "API key"),
        (503, None, "status 503"),
    ],
)
def test_contents_fails_whole_batch_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    payload: Any,
    expected: str,
) -> None:
    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(status_code=status_code, payload=payload)

    monkeypatch.setattr(srezai_module.requests, "post", _mock_post)

    client = SrezaiReadClient(api_key="k")
    results = client.contents(["https://example.ru/a", "https://example.ru/b"])

    assert all(not r.scrape_successful for r in results)
    assert all(expected in (r.failure_reason or "") for r in results)
    assert client.last_error is not None


def test_contents_survives_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(srezai_module.requests, "post", _mock_post)

    results = SrezaiReadClient(api_key="k").contents(["https://example.ru/a"])

    assert len(results) == 1
    assert results[0].scrape_successful is False
    assert "connection refused" in (results[0].failure_reason or "")


def test_contents_empty_input_makes_no_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        raise AssertionError("no request expected")

    monkeypatch.setattr(srezai_module.requests, "post", _mock_post)

    assert SrezaiReadClient(api_key="k").contents([]) == []


def test_build_srezai_content_provider() -> None:
    provider = build_content_provider_from_config(
        provider_type=WebContentProviderType.SREZAI,
        api_key="k",
        config=WebContentProviderConfig(),
    )
    assert isinstance(provider, SrezaiReadClient)
