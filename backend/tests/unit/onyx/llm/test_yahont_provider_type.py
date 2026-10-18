"""The `yahont` provider type is wired into the shared provider tables."""

from onyx.llm.api_surfaces import OPENAI_COMPATIBLE_SURFACES, resolve_api_surface
from onyx.llm.constants import (
    AGGREGATOR_PROVIDERS,
    DYNAMIC_LLM_PROVIDERS,
    PROVIDER_DISPLAY_NAMES,
    SOURCE_API_CONTEXT_LIMIT_PROVIDERS,
    WELL_KNOWN_PROVIDER_NAMES,
    LlmProviderNames,
)
from onyx.llm.yahont_catalog import YAHONT_PROVIDER_NAME
from onyx.server.manage.llm.utils import extract_vendor_from_model_name


def test_yahont_is_a_provider_name() -> None:
    assert LlmProviderNames.YAHONT.value == "yahont"
    assert YAHONT_PROVIDER_NAME == LlmProviderNames.YAHONT.value


def test_yahont_has_a_display_name() -> None:
    assert PROVIDER_DISPLAY_NAMES[LlmProviderNames.YAHONT] == "Yahont"


def test_yahont_is_called_over_the_openai_chat_completions_surface() -> None:
    surface = resolve_api_surface(LlmProviderNames.YAHONT, None)

    assert surface in OPENAI_COMPATIBLE_SURFACES


def test_yahont_stores_its_own_display_names_and_context_limits() -> None:
    # Dynamic: the admin UI shows the stored display name, not a LiteLLM parse.
    assert LlmProviderNames.YAHONT in DYNAMIC_LLM_PROVIDERS
    assert LlmProviderNames.YAHONT in AGGREGATOR_PROVIDERS
    assert LlmProviderNames.YAHONT in SOURCE_API_CONTEXT_LIMIT_PROVIDERS


def test_yahont_is_not_offered_to_admins_as_a_provider_to_add() -> None:
    assert LlmProviderNames.YAHONT not in WELL_KNOWN_PROVIDER_NAMES


def test_yahont_models_group_by_the_vendor_prefix() -> None:
    vendor = extract_vendor_from_model_name(
        "deepseek/deepseek-v4-pro", LlmProviderNames.YAHONT
    )

    assert vendor == "DeepSeek"
