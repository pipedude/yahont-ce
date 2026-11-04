"""Yandex Search API web search: the request carries Russian defaults, the
Base64 XML answer becomes results in Yandex's order, and every failure is a
clear error. The XML shapes below follow live answers checked on 2026-11-04."""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

import onyx.tools.tool_implementations.web_search.clients.yandex_client as yandex_module
from onyx.error_handling.exceptions import OnyxError
from onyx.tools.tool_implementations.web_search.clients.yandex_client import (
    YANDEX_SEARCH_URL,
    YandexSearchClient,
)
from onyx.tools.tool_implementations.web_search.providers import (
    build_search_provider_from_config,
    provider_requires_api_key,
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

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise ValueError("No JSON payload")
        return self._payload


def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)


def _doc(
    url: str,
    title: str,
    *,
    headline: str | None = None,
    passages: tuple[str, ...] = (),
    modtime: str | None = "20261001T155714",
) -> str:
    parts = [
        f"<url>{url}</url>",
        "<domain>example.ru</domain>",
        f"<title>{title}</title>",
    ]
    if headline is not None:
        parts.append(f"<headline>{headline}</headline>")
    if modtime is not None:
        parts.append(f"<modtime>{modtime}</modtime>")
    if passages:
        parts.append(
            "<passages>"
            + "".join(f"<passage>{passage}</passage>" for passage in passages)
            + "</passages>"
        )
    return "<group><doc>" + "".join(parts) + "</doc></group>"


def _answer(*docs: str, error: str | None = None) -> dict[str, Any]:
    response = (
        error
        if error is not None
        else '<reqid>1</reqid><found priority="all">2</found><results><grouping>'
        + "".join(docs)
        + "</grouping></results>"
    )
    xml = f'<?xml version="1.0" encoding="utf-8"?><yandexsearch version="1.0"><response>{response}</response></yandexsearch>'
    return {"rawData": base64.b64encode(xml.encode("utf-8")).decode("ascii")}


def _mock(
    monkeypatch: pytest.MonkeyPatch, *answers: DummyResponse | Exception
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    queue = list(answers)

    def _mock_post(url: str, **kwargs: Any) -> DummyResponse:
        calls.append({"url": url, **kwargs})
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(yandex_module.requests, "post", _mock_post)
    return calls


def test_search_sends_russian_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _mock(monkeypatch, DummyResponse(status_code=200, payload=_answer()))

    YandexSearchClient(api_key="AQVN-key", num_results=20).search(
        "ключевая ставка site:cbr.ru"
    )

    call = calls[0]
    assert call["url"] == YANDEX_SEARCH_URL
    assert call["headers"]["Authorization"] == "Api-Key AQVN-key"
    assert call["allow_redirects"] is False
    assert call["json"] == {
        "query": {
            "searchType": "SEARCH_TYPE_RU",
            "queryText": "ключевая ставка site:cbr.ru",
            "familyMode": "FAMILY_MODE_MODERATE",
            "fixTypoMode": "FIX_TYPO_MODE_ON",
        },
        "groupSpec": {
            "groupMode": "GROUP_MODE_FLAT",
            "groupsOnPage": "20",
            "docsInGroup": "1",
        },
        "maxPassages": "3",
        "region": "225",
        "l10n": "LOCALIZATION_RU",
        "responseFormat": "FORMAT_XML",
    }


@pytest.mark.parametrize(("asked", "sent"), [(0, "1"), (50, "50"), (500, "100")])
def test_search_keeps_the_result_count_in_the_api_range(
    monkeypatch: pytest.MonkeyPatch, asked: int, sent: str
) -> None:
    calls = _mock(monkeypatch, DummyResponse(status_code=200, payload=_answer()))

    YandexSearchClient(api_key="k", num_results=asked).search("q")

    assert calls[0]["json"]["groupSpec"]["groupsOnPage"] == sent


def test_a_long_query_is_cut_at_a_word_to_the_api_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _mock(monkeypatch, DummyResponse(status_code=200, payload=_answer()))

    YandexSearchClient(api_key="k").search("слово " * 100)

    sent: str = calls[0]["json"]["query"]["queryText"]
    assert len(sent) <= 400
    assert sent.endswith("слово")


def test_search_maps_documents_in_yandex_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = _answer(
        _doc(
            "https://www.sravni.ru/rate/",
            "Ключевая <hlword>ставка</hlword> Банка России",
            headline="Банк России планирует еще два заседания",
            passages=("не используется, есть headline",),
        ),
        _doc(
            "https://cbr.ru/hd_base/keyrate/",
            "Ключевая ставка | Банк России",
            passages=(
                "Ключевая <hlword>ставка</hlword>, установленная Советом директоров",
                "действует с 25 октября",
            ),
            modtime=None,
        ),
    )
    _mock(monkeypatch, DummyResponse(status_code=200, payload=answer))

    results = YandexSearchClient(api_key="k").search("ключевая ставка")

    assert [r.link for r in results] == [
        "https://www.sravni.ru/rate/",
        "https://cbr.ru/hd_base/keyrate/",
    ]
    assert results[0].title == "Ключевая ставка Банка России"
    assert results[0].snippet == "Банк России планирует еще два заседания"
    assert results[1].snippet == (
        "Ключевая ставка, установленная Советом директоров действует с 25 октября"
    )


def test_the_yandex_change_time_is_not_passed_as_a_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live answers of 2026-11-04 gave 2014-2018 `modtime` to pages about 2026,
    and the date reaches the model as `updated_at`: a wrong date is worse than none."""
    answer = _answer(_doc("https://ok.ru/", "Ок", modtime="20141022T173819"))
    _mock(monkeypatch, DummyResponse(status_code=200, payload=answer))

    results = YandexSearchClient(api_key="k").search("q")

    assert results[0].published_date is None


def test_a_cyrillic_domain_is_shown_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = _answer(
        _doc(
            "https://xn--h1alcedd.xn--d1aqf.xn--p1ai/instructions/ipoteka/",
            "Ипотека",
        )
    )
    _mock(monkeypatch, DummyResponse(status_code=200, payload=answer))

    results = YandexSearchClient(api_key="k").search("ипотека")

    assert results[0].link == "https://спроси.дом.рф/instructions/ipoteka/"


def test_a_document_without_a_link_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = _answer(_doc("", "Без ссылки"), _doc("https://ok.ru/", "Есть ссылка"))
    _mock(monkeypatch, DummyResponse(status_code=200, payload=answer))

    results = YandexSearchClient(api_key="k").search("q")

    assert [r.link for r in results] == ["https://ok.ru/"]


def test_each_search_is_logged_without_the_query_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The log counts the paid requests: results and time, never the query."""
    answer = _answer(_doc("https://ok.ru/", "Ок"), _doc("https://ya.ru/", "Я"))
    _mock(monkeypatch, DummyResponse(status_code=200, payload=answer))
    logger = MagicMock()
    monkeypatch.setattr(yandex_module, "logger", logger)

    YandexSearchClient(api_key="k").search("секретный запрос")

    logger.info.assert_called_once()
    message = logger.info.call_args.args[0] % logger.info.call_args.args[1:]
    assert "2 results" in message
    assert "секретный запрос" not in message


def test_nothing_found_is_an_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = _answer(error='<error code="15">Sorry, there are no results</error>')
    _mock(monkeypatch, DummyResponse(status_code=200, payload=answer))

    assert YandexSearchClient(api_key="k").search("q") == []


def test_an_xml_error_is_a_clear_error_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_sleep(monkeypatch)
    answer = _answer(error='<error code="32">Daily limit exceeded</error>')
    calls = _mock(monkeypatch, DummyResponse(status_code=200, payload=answer))

    with pytest.raises(ValueError) as raised:
        YandexSearchClient(api_key="k").search("q")

    assert len(calls) == 1
    assert "code 32" in str(raised.value)


def test_an_xml_with_a_dtd_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Yandex never sends a DTD; refusing one rules out entity expansion."""
    _no_sleep(monkeypatch)
    xml = (
        '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        "<yandexsearch><response><results><grouping><group><doc>"
        "<url>https://ok.ru/</url><title>&x;</title>"
        "</doc></group></grouping></results></response></yandexsearch>"
    )
    payload = {"rawData": base64.b64encode(xml.encode()).decode()}
    calls = _mock(monkeypatch, DummyResponse(status_code=200, payload=payload))

    with pytest.raises(ValueError) as raised:
        YandexSearchClient(api_key="k").search("q")

    assert len(calls) == 1
    assert "DTD" in str(raised.value)


@pytest.mark.parametrize(
    "answer",
    [
        DummyResponse(status_code=200, payload={"other": "shape"}),
        DummyResponse(status_code=200, payload={"rawData": "not base64 !!"}),
        DummyResponse(
            status_code=200,
            payload={"rawData": base64.b64encode(b"<not xml").decode()},
        ),
    ],
)
def test_a_malformed_answer_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, answer: DummyResponse
) -> None:
    _no_sleep(monkeypatch)
    _mock(monkeypatch, answer, answer, answer)

    with pytest.raises(ValueError):
        YandexSearchClient(api_key="k").search("q")


def test_search_retries_rate_limits_faults_and_dead_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_sleep(monkeypatch)
    calls = _mock(
        monkeypatch,
        DummyResponse(status_code=429, payload={"code": 8, "message": "quota"}),
        requests.ConnectionError("reset"),
        DummyResponse(status_code=200, payload=_answer(_doc("https://ok.ru/", "Ок"))),
    )

    results = YandexSearchClient(api_key="k").search("q")

    assert len(calls) == 3
    assert [r.link for r in results] == ["https://ok.ru/"]


@pytest.mark.parametrize("status_code", [400, 401, 403])
def test_search_does_not_retry_a_refusal(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    _no_sleep(monkeypatch)
    refusal = DummyResponse(
        status_code=status_code,
        payload={"code": 16, "message": "Unknown api key 'AQVN****abcd'"},
    )
    calls = _mock(monkeypatch, refusal)

    with pytest.raises(ValueError) as raised:
        YandexSearchClient(api_key="k").search("q")

    assert len(calls) == 1
    assert f"status {status_code}" in str(raised.value)
    assert "Unknown api key" in str(raised.value)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (
            DummyResponse(status_code=401, payload={"code": 16, "message": "bad"}),
            "Invalid Yandex Search API key",
        ),
        (
            DummyResponse(status_code=403, payload={"code": 7, "message": "denied"}),
            "search-api.webSearch.user",
        ),
        (
            DummyResponse(
                status_code=200,
                payload=_answer(error='<error code="32">Daily limit</error>'),
            ),
            "limit",
        ),
    ],
)
def test_test_connection_names_the_cause(
    monkeypatch: pytest.MonkeyPatch, answer: DummyResponse, expected: str
) -> None:
    _no_sleep(monkeypatch)
    _mock(monkeypatch, answer, answer, answer)

    with pytest.raises(OnyxError) as raised:
        YandexSearchClient(api_key="k").test_connection()

    assert expected in str(raised.value)


def test_test_connection_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(
        monkeypatch,
        DummyResponse(
            status_code=200, payload=_answer(_doc("https://ya.ru/", "Яндекс"))
        ),
    )

    assert YandexSearchClient(api_key="k").test_connection() == {"status": "ok"}


def test_the_provider_needs_an_api_key() -> None:
    assert provider_requires_api_key(WebSearchProviderType.YANDEX) is True
    with pytest.raises(ValueError):
        build_search_provider_from_config(
            provider_type=WebSearchProviderType.YANDEX, api_key=None, config={}
        )


def test_the_factory_builds_the_client() -> None:
    provider = build_search_provider_from_config(
        provider_type=WebSearchProviderType.YANDEX,
        api_key="AQVN-key",
        config={"num_results": "7"},
    )

    assert isinstance(provider, YandexSearchClient)
    assert provider.supports_site_filter is True
