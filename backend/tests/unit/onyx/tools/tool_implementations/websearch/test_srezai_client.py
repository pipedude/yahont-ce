from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

import pytest
import requests

import onyx.tools.tool_implementations.web_search.clients.srezai_client as srezai_module
from onyx.error_handling.exceptions import OnyxError
from onyx.tools.tool_implementations.web_search.clients.srezai_client import (
    SREZAI_SEARCH_URL,
    SrezaiSearchClient,
)
from onyx.tools.tool_implementations.web_search.providers import (
    build_search_provider_from_config,
)
from shared_configs.enums import WebSearchProviderType


class DummyResponse:
    def __init__(
        self,
        *,
        status_code: int,
        payload: dict[str, Any] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            http_error = requests.HTTPError(f"{self.status_code} Client Error")
            http_error.response = cast(requests.Response, self)
            raise http_error

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise ValueError("No JSON payload")
        return self._payload


def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)


def _result(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": " Ключевая ставка ",
        "url": "https://example.ru/rate",
        "content": "Банк России сохранил ставку.",
        "publishedDate": "2026-09-11T13:31:00",
        "relevance": 0.8,
        "semantic": 0.9,
    }
    base.update(overrides)
    return base


def test_search_sends_russian_friendly_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _mock_post(url: str, **kwargs: Any) -> DummyResponse:
        captured["url"] = url
        captured.update(kwargs)
        return DummyResponse(status_code=200, payload={"results": []})

    monkeypatch.setattr(srezai_module.requests, "post", _mock_post)

    SrezaiSearchClient(api_key="srz_live_test", num_results=50).search(
        "site:habr.com fastapi"
    )

    assert captured["url"] == SREZAI_SEARCH_URL
    assert captured["headers"]["Authorization"] == "Bearer srz_live_test"
    assert captured["json"] == {
        "query": "site:habr.com fastapi",
        "num": 30,
        "language": "auto",
        "category": "general",
    }
    assert captured["allow_redirects"] is False


def test_search_maps_results_and_drops_irrelevant_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            status_code=200,
            payload={
                "results": [
                    _result(),
                    # Unrelated page: both relevance signals are zero.
                    _result(
                        url="https://en.wikipedia.org/wiki/Dentist",
                        relevance=0,
                        semantic=0.00002,
                    ),
                    # Reranker off: a zero lexical score alone is kept.
                    _result(
                        url="https://example.ru/no-rerank",
                        relevance=0,
                        semantic=None,
                        publishedDate=None,
                    ),
                    _result(url=""),
                    "not-a-dict",
                ]
            },
        )

    monkeypatch.setattr(srezai_module.requests, "post", _mock_post)

    results = SrezaiSearchClient(api_key="k").search("ключевая ставка")

    assert [r.link for r in results] == [
        "https://example.ru/rate",
        "https://example.ru/no-rerank",
    ]
    assert results[0].title == "Ключевая ставка"
    assert results[0].snippet == "Банк России сохранил ставку."
    assert results[0].published_date == datetime(
        2026, 9, 11, 13, 31, tzinfo=timezone.utc
    )
    assert results[1].published_date is None


def test_search_retries_transient_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_sleep(monkeypatch)
    responses = [
        DummyResponse(
            status_code=503,
            payload={"error": "Движки не ответили", "code": "search_unavailable"},
        ),
        DummyResponse(
            status_code=429,
            payload={"error": "Слишком много запросов", "reason": "burst"},
        ),
        DummyResponse(status_code=200, payload={"results": [_result()]}),
    ]

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return responses.pop(0)

    monkeypatch.setattr(srezai_module.requests, "post", _mock_post)

    results = SrezaiSearchClient(api_key="k").search("q")

    assert len(results) == 1
    assert responses == []


def test_search_does_not_retry_client_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_sleep(monkeypatch)
    calls = {"count": 0}

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        calls["count"] += 1
        return DummyResponse(
            status_code=402,
            payload={"error": "Недостаточно кредитов", "code": "insufficient_funds"},
        )

    monkeypatch.setattr(srezai_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="insufficient_funds"):
        SrezaiSearchClient(api_key="k").search("q")
    assert calls["count"] == 1


def test_search_rejects_unexpected_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(status_code=200, payload={"results": {"x": 1}})

    monkeypatch.setattr(srezai_module.requests, "post", _mock_post)

    with pytest.raises(ValueError, match="unexpected response"):
        SrezaiSearchClient(api_key="k").search("q")


@pytest.mark.parametrize(
    ("status_code", "code", "expected"),
    [
        (401, "unauthorized", "Invalid srezai.ru API key"),
        (402, "insufficient_funds", "no credits left"),
        (400, "bad_request", "srezai.ru API key validation failed"),
    ],
)
def test_test_connection_maps_errors(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    code: str,
    expected: str,
) -> None:
    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            status_code=status_code, payload={"error": "ошибка", "code": code}
        )

    monkeypatch.setattr(srezai_module.requests, "post", _mock_post)

    with pytest.raises(OnyxError, match=expected):
        SrezaiSearchClient(api_key="k").test_connection()


def test_test_connection_requires_results(monkeypatch: pytest.MonkeyPatch) -> None:
    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(status_code=200, payload={"results": []})

    monkeypatch.setattr(srezai_module.requests, "post", _mock_post)

    with pytest.raises(OnyxError, match="no results"):
        SrezaiSearchClient(api_key="k").test_connection()


def test_test_connection_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(status_code=200, payload={"results": [_result()]})

    monkeypatch.setattr(srezai_module.requests, "post", _mock_post)

    assert SrezaiSearchClient(api_key="k").test_connection() == {"status": "ok"}


def test_build_srezai_provider_requires_api_key() -> None:
    with pytest.raises(ValueError, match="API key is required"):
        build_search_provider_from_config(
            provider_type=WebSearchProviderType.SREZAI,
            api_key=None,
            config={},
        )


def test_srezai_key_is_shared_between_search_and_content() -> None:
    from onyx.server.manage.web_search.api import (
        _CONTENT_TO_SEARCH_SYNC,
        _SEARCH_TO_CONTENT_SYNC,
    )
    from shared_configs.enums import WebContentProviderType

    assert (
        WebSearchProviderType.SREZAI,
        "Srezai",
        WebContentProviderType.SREZAI,
    ) in _SEARCH_TO_CONTENT_SYNC
    assert (
        WebContentProviderType.SREZAI,
        "Srezai",
        WebSearchProviderType.SREZAI,
    ) in _CONTENT_TO_SEARCH_SYNC


def test_build_srezai_provider() -> None:
    provider = build_search_provider_from_config(
        provider_type=WebSearchProviderType.SREZAI,
        api_key="k",
        config={"num_results": "7"},
    )
    assert isinstance(provider, SrezaiSearchClient)
    assert provider.supports_site_filter is True
