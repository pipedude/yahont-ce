"""RouterAI and Polza.ai are wired in as OpenAI-compatible gateway providers.

Both speak the OpenAI Chat Completions protocol. They have no LiteLLM
integration, so calls go over a static OpenAI-compatible surface (like Nebius
TokenFactory), never through LiteLLM's `openrouter/` route.
"""

from unittest.mock import patch

import pytest

from onyx.llm.api_surfaces import (
    OPENAI_COMPATIBLE_SURFACES,
    LlmApiSurface,
    resolve_api_surface,
)
from onyx.llm.constants import (
    AGGREGATOR_PROVIDERS,
    DYNAMIC_LLM_PROVIDERS,
    PROVIDER_DISPLAY_NAMES,
    SOURCE_API_CONTEXT_LIMIT_PROVIDERS,
    WELL_KNOWN_PROVIDER_NAMES,
    LlmProviderNames,
)
from onyx.llm.model_request import ChatCompletionMessage, UserMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.well_known_providers.constants import (
    POLZA_DEFAULT_API_BASE,
    POLZA_PROVIDER_NAME,
    ROUTERAI_DEFAULT_API_BASE,
    ROUTERAI_PROVIDER_NAME,
)
from onyx.llm.well_known_providers.llm_provider_options import (
    get_provider_display_name,
)
from onyx.server.manage.llm.utils import extract_vendor_from_model_name

_PROVIDERS = [LlmProviderNames.ROUTERAI, LlmProviderNames.POLZA]

_WITH_BASE = [
    (LlmProviderNames.ROUTERAI, "https://routerai.ru/api/v1"),
    (LlmProviderNames.POLZA, "https://polza.ai/api/v1"),
]


@pytest.mark.parametrize(
    "provider,value,display",
    [
        (LlmProviderNames.ROUTERAI, "routerai", "RouterAI"),
        (LlmProviderNames.POLZA, "polza", "Polza.ai"),
    ],
)
def test_provider_names_and_display_names(
    provider: LlmProviderNames, value: str, display: str
) -> None:
    assert provider.value == value
    assert PROVIDER_DISPLAY_NAMES[provider] == display
    assert get_provider_display_name(value) == display


def test_provider_name_constants_and_default_bases() -> None:
    assert ROUTERAI_PROVIDER_NAME == LlmProviderNames.ROUTERAI.value
    assert POLZA_PROVIDER_NAME == LlmProviderNames.POLZA.value
    assert ROUTERAI_DEFAULT_API_BASE == "https://routerai.ru/api/v1"
    assert POLZA_DEFAULT_API_BASE == "https://polza.ai/api/v1"


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_gateway_is_offered_to_admins_as_a_provider_to_add(
    provider: LlmProviderNames,
) -> None:
    assert provider in WELL_KNOWN_PROVIDER_NAMES


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_gateway_stores_its_own_display_names_and_context_limits(
    provider: LlmProviderNames,
) -> None:
    assert provider in AGGREGATOR_PROVIDERS
    assert provider in DYNAMIC_LLM_PROVIDERS
    assert provider in SOURCE_API_CONTEXT_LIMIT_PROVIDERS


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_gateway_is_called_over_the_openai_chat_completions_surface(
    provider: LlmProviderNames,
) -> None:
    surface = resolve_api_surface(provider, None)

    assert surface is LlmApiSurface.OPENAI_CHAT_COMPLETIONS
    assert surface in OPENAI_COMPATIBLE_SURFACES


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_gateway_models_group_by_the_vendor_prefix(
    provider: LlmProviderNames,
) -> None:
    vendor = extract_vendor_from_model_name("anthropic/claude-sonnet-4.5", provider)

    assert vendor == "Anthropic"


def _make_llm(provider: LlmProviderNames, api_base: str) -> LitellmLLM:
    return LitellmLLM(
        api_key="test-key",
        model_provider=provider,
        model_name="deepseek/deepseek-v4-pro",
        max_input_tokens=128_000,
        api_base=api_base,
    )


def _completion_kwargs(llm: LitellmLLM) -> dict:
    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []
        messages: list[ChatCompletionMessage] = [UserMessage(content="Hi")]
        list(llm.stream_raw(messages))
        return dict(mock_completion.call_args.kwargs)


@pytest.mark.parametrize("provider,base", _WITH_BASE)
def test_calls_use_the_openai_client_with_a_bare_model_name(
    provider: LlmProviderNames, base: str
) -> None:
    kwargs = _completion_kwargs(_make_llm(provider, base))

    assert kwargs["custom_llm_provider"] == "openai"
    assert kwargs["base_url"] == base
    # The gateway namespaces models as `vendor/model`; send the id unchanged.
    assert kwargs["model"] == "deepseek/deepseek-v4-pro"


@pytest.mark.parametrize("provider,base", _WITH_BASE)
def test_bare_base_url_is_coerced_to_v1(provider: LlmProviderNames, base: str) -> None:
    bare = base.removesuffix("/v1")
    llm = _make_llm(provider, bare)

    assert llm._api_base == f"{bare}/v1"
