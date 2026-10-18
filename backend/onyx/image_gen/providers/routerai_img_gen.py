from __future__ import annotations

from typing import TYPE_CHECKING, Any

from onyx.image_gen.interfaces import (
    ImageGenerationProvider,
    ImageGenerationProviderCredentials,
    ReferenceImage,
)
from onyx.image_gen.providers.gateway_http import (
    aspect_ratio_for_size,
    build_image_response,
    post_json,
    to_data_uri,
)
from onyx.llm.well_known_providers.constants import (
    ROUTERAI_DEFAULT_API_BASE,
    ROUTERAI_PROVIDER_NAME,
)
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call

if TYPE_CHECKING:
    from onyx.image_gen.interfaces import ImageGenerationResponse

_GATEWAY = "RouterAI"
_TIMEOUT_SECONDS = 300


class RouterAIImageGenerationProvider(ImageGenerationProvider):
    """routerai.ru ``POST /images``: one endpoint for GPT Image and Gemini models.

    Model ids keep their vendor prefix (``openai/gpt-image-2.5-flare``).
    """

    def __init__(self, api_key: str, api_base: str | None = None) -> None:
        self._api_key = api_key
        self._api_base = (api_base or ROUTERAI_DEFAULT_API_BASE).rstrip("/")

    @classmethod
    def validate_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> bool:
        return bool(credentials.api_key)

    @classmethod
    def _build_from_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> RouterAIImageGenerationProvider:
        assert credentials.api_key
        return cls(api_key=credentials.api_key, api_base=credentials.api_base)

    @property
    def supports_reference_images(self) -> bool:
        return True

    @property
    def max_reference_images(self) -> int:
        return 10

    def generate_image(
        self,
        prompt: str,
        model: str,
        size: str,
        n: int,
        quality: str | None = None,
        reference_images: list[ReferenceImage] | None = None,
        **kwargs: Any,  # noqa: ARG002 - response_format: the gateway always returns base64
    ) -> ImageGenerationResponse:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": n,
            "aspect_ratio": aspect_ratio_for_size(size),
        }
        if quality:
            payload["quality"] = quality
        if reference_images:
            payload["input_references"] = [
                {"type": "image_url", "image_url": {"url": to_data_uri(image)}}
                for image in reference_images
            ]

        with traced_llm_call(
            flow=LLMFlow.IMAGE_EDIT if reference_images else LLMFlow.IMAGE_GENERATION,
            model=model,
            provider=ROUTERAI_PROVIDER_NAME,
            image_count=n,
            input_messages=[{"role": "user", "content": prompt}],
        ):
            body = post_json(
                f"{self._api_base}/images",
                self._api_key,
                payload,
                _GATEWAY,
                _TIMEOUT_SECONDS,
            )
        return build_image_response(body.get("data"), prompt, _GATEWAY)
