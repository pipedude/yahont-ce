from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from onyx.image_gen.interfaces import (
    ImageGenerationProvider,
    ImageGenerationProviderCredentials,
    ReferenceImage,
)
from onyx.image_gen.providers.gateway_http import (
    aspect_ratio_for_size,
    build_image_response,
    gateway_error,
    get_json,
    post_json,
    to_data_uri,
)
from onyx.llm.exceptions import ClassifiedLLMError
from onyx.llm.well_known_providers.constants import (
    POLZA_DEFAULT_API_BASE,
    POLZA_PROVIDER_NAME,
)
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from onyx.image_gen.interfaces import ImageGenerationResponse

logger = setup_logger()

_GATEWAY = "Polza.ai"
# Async mode: the task id comes back at once and the status is polled. A sync
# GPT Image 2.5 run can take over 3 minutes, longer than any sane read timeout.
_REQUEST_TIMEOUT_SECONDS = 60
_STATUS_TIMEOUT_SECONDS = 30
_POLL_INTERVAL_SECONDS = 3
_MAX_TOTAL_SECONDS = 600
_PENDING_STATUSES = {"pending", "processing"}


class PolzaImageGenerationProvider(ImageGenerationProvider):
    """polza.ai Media API (``POST /media``): every image model, with references.

    Results come back as public CDN links, so the image is downloaded and
    passed on as base64. Model ids keep their vendor prefix.
    """

    def __init__(self, api_key: str, api_base: str | None = None) -> None:
        self._api_key = api_key
        self._api_base = (api_base or POLZA_DEFAULT_API_BASE).rstrip("/")

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
    ) -> PolzaImageGenerationProvider:
        assert credentials.api_key
        return cls(api_key=credentials.api_key, api_base=credentials.api_base)

    @property
    def supports_reference_images(self) -> bool:
        return True

    @property
    def max_reference_images(self) -> int:
        # Nano Banana 2.1 accepts up to 10 references, GPT Image 2.5 up to 16.
        return 10

    def generate_image(
        self,
        prompt: str,
        model: str,
        size: str,
        n: int,
        quality: str | None = None,  # noqa: ARG002 - not a Media API input for these models
        reference_images: list[ReferenceImage] | None = None,
        **kwargs: Any,  # noqa: ARG002 - response_format: results are always links
    ) -> ImageGenerationResponse:
        image_input: dict[str, Any] = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio_for_size(size),
        }
        if reference_images:
            image_input["images"] = [
                {"type": "base64", "data": to_data_uri(image)}
                for image in reference_images
            ]

        with traced_llm_call(
            flow=LLMFlow.IMAGE_EDIT if reference_images else LLMFlow.IMAGE_GENERATION,
            model=model,
            provider=POLZA_PROVIDER_NAME,
            image_count=n,
            input_messages=[{"role": "user", "content": prompt}],
        ):
            body = post_json(
                f"{self._api_base}/media",
                self._api_key,
                {"model": model, "input": image_input, "async": True},
                _GATEWAY,
                _REQUEST_TIMEOUT_SECONDS,
            )
            body = self._wait_for_completion(body)
        return build_image_response(body.get("data"), prompt, _GATEWAY)

    def _wait_for_completion(self, body: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + _MAX_TOTAL_SECONDS
        while body.get("status") in _PENDING_STATUSES:
            generation_id = body.get("id")
            if not generation_id or time.monotonic() > deadline:
                raise gateway_error(
                    _GATEWAY,
                    "the generation did not finish in time.",
                    "CONNECTION_ERROR",
                    True,
                )
            time.sleep(_POLL_INTERVAL_SECONDS)
            try:
                body = get_json(
                    f"{self._api_base}/media/{generation_id}",
                    self._api_key,
                    _GATEWAY,
                    _STATUS_TIMEOUT_SECONDS,
                )
            except ClassifiedLLMError as e:
                # The paid generation goes on at Polza: a network blip or a 5xx
                # on one status request must not lose its result.
                if not e.is_retryable:
                    raise
                logger.warning(
                    "Polza status poll for %s failed, retrying: %s",
                    generation_id,
                    e.client_error_msg,
                )

        if body.get("status") != "completed":
            error = body.get("error")
            reason = (
                error.get("message")
                if isinstance(error, dict) and error.get("message")
                else f"status {body.get('status')}"
            )
            raise gateway_error(
                _GATEWAY, f"generation failed: {reason}", "API_ERROR", False
            )
        return body
