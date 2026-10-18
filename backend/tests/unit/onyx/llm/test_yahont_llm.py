"""The `yahont` provider in the LLM factory, cost tracking and admission.

An `yahont` provider row holds no upstream key. The factory takes the upstream
model name, key and base URL from the catalog and env, per model. The managed
key set makes the admission check and the cost tracker treat these calls as
platform spend.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm import yahont_catalog
from onyx.llm.factory import llm_from_provider
from onyx.llm.model_request import UserMessage
from onyx.llm.models import Usage
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.yahont_catalog import (
    YAHONT_MANAGED_KEY_SENTINEL,
    YAHONT_PROVIDER_NAME,
    YahontCatalog,
    YahontRoute,
)
from onyx.server.manage.llm.models import LLMProviderView, ModelConfigurationView
from onyx.server.usage_limits import (
    check_llm_cost_limit_for_provider,
    is_onyx_managed_api_key,
)

_MODEL_ID = "google/gemini-3.8-flash"


def _yahont_provider_view() -> LLMProviderView:
    return LLMProviderView(
        id=1,
        name="Yahont",
        provider=YAHONT_PROVIDER_NAME,
        model_configurations=[
            ModelConfigurationView(
                name=_MODEL_ID,
                is_visible=True,
                max_input_tokens=1_000_000,
                supports_image_input=True,
            )
        ],
        api_key=YAHONT_MANAGED_KEY_SENTINEL,
        api_base=None,
        api_version=None,
        custom_config=None,
        is_public=True,
        is_auto_mode=False,
        groups=[],
        personas=[],
        deployment_name=None,
    )


def _catalog() -> YahontCatalog:
    return YahontCatalog.model_validate(
        {
            "version": "1",
            "updated_at": "2026-10-01",
            "rub_per_usd": 100.0,
            "models": [
                {
                    "id": _MODEL_ID,
                    "display_name": "Gemini 3.8 Flash",
                    "upstream": "routerai",
                    "upstream_model": "google/gemini-3.8-flash",
                    "input_price_rub_per_mtok": 200.0,
                    "output_price_rub_per_mtok": 400.0,
                    "max_input_tokens": 1_000_000,
                    "vision": True,
                    "reasoning": True,
                    "default": True,
                }
            ],
        }
    )


def test_llm_from_provider_routes_an_yahont_model_to_its_upstream() -> None:
    route = YahontRoute(
        upstream_model="vendor/upstream-name",
        api_key="router-key",
        api_base="https://routerai.example/api/v1",
    )
    with (
        patch("onyx.llm.factory.resolve_yahont_route", return_value=route),
        patch("onyx.llm.factory.get_llm") as mock_get_llm,
    ):
        llm_from_provider(model_name=_MODEL_ID, llm_provider=_yahont_provider_view())

    kwargs = mock_get_llm.call_args.kwargs
    assert kwargs["provider"] == YAHONT_PROVIDER_NAME
    # Identity and billing stay on the catalog id; the upstream gets its own name.
    assert kwargs["model"] == _MODEL_ID
    assert kwargs["deployment_name"] == "vendor/upstream-name"
    assert kwargs["api_key"] == "router-key"
    assert kwargs["api_base"] == "https://routerai.example/api/v1"
    assert kwargs["max_input_tokens"] == 1_000_000


def test_llm_from_provider_refuses_an_yahont_model_outside_the_catalog() -> None:
    not_found = OnyxError(OnyxErrorCode.NOT_FOUND, "not in the Yahont catalog")
    with (
        patch("onyx.llm.factory.resolve_yahont_route", side_effect=not_found),
        patch("onyx.llm.factory.get_llm") as mock_get_llm,
    ):
        with pytest.raises(OnyxError) as excinfo:
            llm_from_provider(
                model_name="anthropic/claude-opus-5",
                llm_provider=_yahont_provider_view(),
            )

    assert excinfo.value.error_code is OnyxErrorCode.NOT_FOUND
    mock_get_llm.assert_not_called()


def test_llm_from_provider_leaves_other_providers_untouched() -> None:
    provider = _yahont_provider_view().model_copy(
        update={
            "provider": "openai",
            "api_key": "tenant-own-key",
            "api_base": "https://tenant.example/v1",
        }
    )
    with (
        patch("onyx.llm.factory.resolve_yahont_route") as mock_route,
        patch("onyx.llm.factory.get_llm") as mock_get_llm,
    ):
        llm_from_provider(model_name=_MODEL_ID, llm_provider=provider)

    mock_route.assert_not_called()
    kwargs = mock_get_llm.call_args.kwargs
    assert kwargs["api_key"] == "tenant-own-key"
    assert kwargs["api_base"] == "https://tenant.example/v1"
    assert kwargs["deployment_name"] is None


def test_yahont_llm_sends_the_upstream_name_to_litellm() -> None:
    llm = LitellmLLM(
        api_key="router-key",
        api_base="https://routerai.example/api/v1",
        model_provider=YAHONT_PROVIDER_NAME,
        model_name=_MODEL_ID,
        deployment_name="vendor/upstream-name",
        max_input_tokens=1_000_000,
    )

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []
        list(llm.stream_raw([UserMessage(content="hi")]))

    kwargs = mock_completion.call_args.kwargs
    assert kwargs["model"] == "vendor/upstream-name"
    assert kwargs["api_key"] == "router-key"
    assert kwargs["api_base"] == "https://routerai.example/api/v1"
    assert kwargs["custom_llm_provider"] == "openai"


@contextmanager
def _tracking_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[MagicMock, MagicMock]]:
    db_session = MagicMock()

    @contextmanager
    def _fake_session() -> Iterator[Any]:
        yield db_session

    increment_usage = MagicMock()
    forbidden_catalog_price = MagicMock(
        side_effect=AssertionError("yahont calls must not use the vendored price table")
    )
    monkeypatch.setattr(
        "onyx.server.usage_limits._ONYX_MANAGED_API_KEYS", {"router-key"}
    )
    monkeypatch.setattr(
        "onyx.db.engine.sql_engine.get_session_with_current_tenant", _fake_session
    )
    monkeypatch.setattr("onyx.db.usage.increment_usage", increment_usage)
    monkeypatch.setattr(
        "onyx.db.credit_wallet.spend_credit_wallet",
        lambda _session, _cents: (10.0, 9.0),
    )
    monkeypatch.setattr(
        "onyx.llm.multi_llm.compute_cost_cents", forbidden_catalog_price
    )
    with patch.object(yahont_catalog, "get_yahont_catalog", return_value=_catalog()):
        yield increment_usage, forbidden_catalog_price


def _yahont_llm(api_key: str = "router-key", model: str = _MODEL_ID) -> LitellmLLM:
    return LitellmLLM(
        api_key=api_key,
        model_provider=YAHONT_PROVIDER_NAME,
        model_name=model,
        deployment_name="google/gemini-3.8-flash",
        max_input_tokens=1_000_000,
    )


_USAGE = Usage(
    prompt_tokens=1000,
    completion_tokens=500,
    total_tokens=1500,
    cache_read_input_tokens=0,
    cache_creation_input_tokens=0,
)


def test_yahont_call_is_debited_at_the_catalog_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _tracking_environment(monkeypatch) as (increment_usage, _):
        _yahont_llm()._track_llm_cost(_USAGE)

    # Input 200 RUB/Mtok and output 400 RUB/Mtok at 100 RUB per USD:
    # 1000 tokens -> 0.2 cents, 500 tokens -> 0.2 cents.
    increment_usage.assert_called_once()
    assert increment_usage.call_args.args[2] == pytest.approx(0.4)


def test_yahont_call_outside_the_catalog_is_not_debited_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _tracking_environment(monkeypatch) as (increment_usage, _):
        _yahont_llm(model="no/such-model")._track_llm_cost(_USAGE)

    increment_usage.assert_not_called()


def test_yahont_call_on_an_unmanaged_key_is_not_debited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _tracking_environment(monkeypatch) as (increment_usage, _):
        _yahont_llm(api_key="some-other-key")._track_llm_cost(_USAGE)

    increment_usage.assert_not_called()


def test_the_row_marker_counts_as_a_managed_key() -> None:
    assert is_onyx_managed_api_key(YAHONT_MANAGED_KEY_SENTINEL)


def test_admission_runs_for_the_yahont_row_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gateway passes the provider row key, which is the marker."""
    admission = MagicMock()
    monkeypatch.setattr(
        "onyx.server.usage_limits.is_tenant_on_trial_fn", lambda _tid: False
    )
    monkeypatch.setattr("onyx.server.usage_limits.check_wallet_admission", admission)

    check_llm_cost_limit_for_provider(
        db_session=MagicMock(),
        tenant_id="tenant_abc",
        llm_provider_api_key=YAHONT_MANAGED_KEY_SENTINEL,
    )

    admission.assert_called_once()
