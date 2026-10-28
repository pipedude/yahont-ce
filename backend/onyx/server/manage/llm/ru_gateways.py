"""RouterAI and Polza.ai gateways: model-list request/response and parsing.

Both gateways speak the OpenAI Chat Completions protocol and publish an
OpenRouter-style `/models` catalog that mixes chat, media and embedding models.
They differ in where the context length and the supported parameters live:
RouterAI keeps them at the top level of each entry, Polza.ai under
`top_provider`.
"""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_capabilities import model_is_reasoning_model
from onyx.llm.model_catalog import resolve_model_mode
from onyx.server.manage.llm.utils import (
    is_reasoning_model,
    strip_openrouter_vendor_prefix,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


class GatewayModelsRequest(BaseModel):
    # Both fields are optional: the default base fills in and a public catalog
    # needs no key.
    api_base: str | None = None
    api_key: str | None = None
    # Existing provider id; resolves the stored key and syncs fetched models on edit
    provider_id: int | None = None


class GatewayFinalModelResponse(BaseModel):
    name: str  # Model id in `vendor/model` form (e.g. "anthropic/claude-sonnet-4.5")
    display_name: str
    max_input_tokens: int | None
    supports_image_input: bool
    supports_reasoning: bool


def gateway_models_url(api_base: str) -> str:
    """The `/models` URL for a base given with or without the `/v1` suffix."""
    base = api_base.strip().rstrip("/")
    return f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"


def _routerai_details(model: dict[str, Any]) -> tuple[Any, Any]:
    return model.get("context_length"), model.get("supported_parameters")


def _polza_details(model: dict[str, Any]) -> tuple[Any, Any]:
    top_provider = model.get("top_provider") or {}
    return (
        top_provider.get("context_length") or model.get("context_length"),
        top_provider.get("supported_parameters"),
    )


# provider -> (context length, supported parameters) of one catalog entry
_DETAILS: dict[str, Callable[[dict[str, Any]], tuple[Any, Any]]] = {
    LlmProviderNames.ROUTERAI: _routerai_details,
    LlmProviderNames.POLZA: _polza_details,
}


def _outputs_text_only(architecture: dict[str, Any]) -> bool:
    """Chat models answer in text; image, video, audio and embedding models do not.

    An entry without output modalities is treated as a text model.
    """
    output_modalities = architecture.get("output_modalities")
    if not isinstance(output_modalities, list) or not output_modalities:
        return True
    return set(output_modalities) == {"text"}


def _supports_reasoning(
    model_id: str,
    display_name: str,
    supported_parameters: Any,
    provider: LlmProviderNames,
) -> bool:
    if isinstance(supported_parameters, list):
        return "reasoning" in supported_parameters
    # No parameter data from the gateway: LiteLLM cost map, then name heuristic.
    return model_is_reasoning_model(model_id, provider) or is_reasoning_model(
        model_id, display_name
    )


def parse_gateway_models(
    models: list[Any], provider: LlmProviderNames
) -> list[GatewayFinalModelResponse]:
    """Keep the text chat models of a gateway catalog, with their capabilities."""
    read_details = _DETAILS[provider]
    results: list[GatewayFinalModelResponse] = []
    for model in models:
        try:
            model_id = model.get("id") or ""
            if not model_id or resolve_model_mode(model_id) == "embedding":
                continue
            if model.get("type", "chat") != "chat":
                continue
            architecture = model.get("architecture") or {}
            if not _outputs_text_only(architecture):
                continue

            context_length, supported_parameters = read_details(model)
            display_name = strip_openrouter_vendor_prefix(
                model.get("name") or model_id, model_id
            )
            results.append(
                GatewayFinalModelResponse(
                    name=model_id,
                    display_name=display_name,
                    max_input_tokens=context_length or None,
                    supports_image_input="image"
                    in (architecture.get("input_modalities") or []),
                    supports_reasoning=_supports_reasoning(
                        model_id, display_name, supported_parameters, provider
                    ),
                )
            )
        except Exception as e:
            logger.warning(
                "Failed to parse %s model entry",
                provider.value,
                extra={"error": str(e), "item": str(model)[:1000]},
            )
    return results
