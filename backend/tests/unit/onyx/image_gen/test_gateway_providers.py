"""RouterAI and Polza.ai image generation: tenant-owned keys (BYOK) only."""

import base64
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.image_gen.exceptions import ImageProviderCredentialsError
from onyx.image_gen.factory import get_image_generation_provider
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials, ReferenceImage
from onyx.image_gen.providers.polza_img_gen import PolzaImageGenerationProvider
from onyx.image_gen.providers.routerai_img_gen import RouterAIImageGenerationProvider
from onyx.llm.exceptions import ClassifiedLLMError

_HTTP = "onyx.image_gen.providers.gateway_http.requests"
_POLL_SLEEP = "onyx.image_gen.providers.polza_img_gen.time.sleep"

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake"
PNG_B64 = base64.b64encode(PNG_BYTES).decode()


def _response(status: int, body: Any = None, content: bytes = b"") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body
    resp.text = str(body)
    resp.content = content
    return resp


def _first_b64(result: Any) -> str | None:
    assert result.data
    return result.data[0].b64_json


def _creds(
    api_key: str | None = "user-key", api_base: str | None = None
) -> ImageGenerationProviderCredentials:
    return ImageGenerationProviderCredentials(api_key=api_key, api_base=api_base)


# --- factory -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "cls", "default_base"),
    [
        ("routerai", RouterAIImageGenerationProvider, "https://routerai.ru/api/v1"),
        ("polza", PolzaImageGenerationProvider, "https://polza.ai/api/v1"),
    ],
)
def test_factory_builds_gateway_with_default_base(
    provider: str, cls: type, default_base: str
) -> None:
    built = get_image_generation_provider(provider, _creds())

    assert isinstance(built, cls)
    assert isinstance(
        built, (RouterAIImageGenerationProvider, PolzaImageGenerationProvider)
    )
    assert built._api_base == default_base
    assert built.supports_reference_images is True
    assert built.max_reference_images > 0


@pytest.mark.parametrize("provider", ["routerai", "polza"])
def test_factory_keeps_admin_api_base(provider: str) -> None:
    built = get_image_generation_provider(
        provider, _creds(api_base="https://proxy.example.com/v1/")
    )

    assert isinstance(
        built, (RouterAIImageGenerationProvider, PolzaImageGenerationProvider)
    )
    assert built._api_base == "https://proxy.example.com/v1"


@pytest.mark.parametrize("provider", ["routerai", "polza"])
def test_factory_requires_api_key(provider: str) -> None:
    with pytest.raises(ImageProviderCredentialsError):
        get_image_generation_provider(provider, _creds(api_key=None))


# --- RouterAI ----------------------------------------------------------------


def test_routerai_generates_with_full_model_id_and_aspect_ratio() -> None:
    provider = RouterAIImageGenerationProvider(api_key="user-key")
    body = {"data": [{"b64_json": PNG_B64}], "usage": {"cost": 0.66}}

    with patch(f"{_HTTP}.post", return_value=_response(200, body)) as post:
        result = provider.generate_image(
            prompt="a green square",
            model="openai/gpt-image-2.5-flare",
            size="1536x1024",
            n=1,
            quality="low",
            response_format=None,
        )

    url = post.call_args.args[0]
    payload = post.call_args.kwargs["json"]
    assert url == "https://routerai.ru/api/v1/images"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer user-key"
    assert payload == {
        "model": "openai/gpt-image-2.5-flare",
        "prompt": "a green square",
        "n": 1,
        "aspect_ratio": "3:2",
        "quality": "low",
    }
    assert _first_b64(result) == PNG_B64


def test_routerai_sends_reference_images_as_data_uris() -> None:
    provider = RouterAIImageGenerationProvider(api_key="user-key")
    body = {"data": [{"b64_json": PNG_B64}]}

    with patch(f"{_HTTP}.post", return_value=_response(200, body)) as post:
        provider.generate_image(
            prompt="paint the circle yellow",
            model="google/gemini-3.1-flash-image",
            size="1024x1024",
            n=1,
            reference_images=[ReferenceImage(data=PNG_BYTES, mime_type="image/png")],
        )

    payload = post.call_args.kwargs["json"]
    assert payload["aspect_ratio"] == "1:1"
    assert "quality" not in payload
    assert payload["input_references"] == [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{PNG_B64}"},
        }
    ]


@pytest.mark.parametrize(
    ("status", "error_code", "retryable"),
    [
        (401, "AUTH_ERROR", False),
        (402, "BUDGET_EXCEEDED", False),
        (400, "BAD_REQUEST", False),
        (429, "RATE_LIMIT", True),
        (503, "SERVICE_UNAVAILABLE", True),
    ],
)
def test_routerai_maps_http_errors(
    status: int, error_code: str, retryable: bool
) -> None:
    provider = RouterAIImageGenerationProvider(api_key="user-key")
    body = {"error": {"message": "upstream says no", "code": status}}

    with (
        patch(f"{_HTTP}.post", return_value=_response(status, body)),
        pytest.raises(ClassifiedLLMError) as exc_info,
    ):
        provider.generate_image(
            prompt="x", model="openai/gpt-image-2.5-flare", size="1024x1024", n=1
        )

    assert exc_info.value.error_code == error_code
    assert exc_info.value.is_retryable is retryable
    assert "RouterAI" in exc_info.value.client_error_msg


def test_routerai_safety_rejection_in_200_body_is_content_policy() -> None:
    # Seen live: RouterAI answers HTTP 200 with an error body when OpenAI's
    # safety system refuses the prompt (a brand name in the prompt).
    provider = RouterAIImageGenerationProvider(api_key="user-key")
    body = {
        "error": {
            "message": "Your request was rejected by the safety system.",
            "code": 400,
            "metadata": {"provider_name": "OpenAI"},
        }
    }

    with (
        patch(f"{_HTTP}.post", return_value=_response(200, body)),
        pytest.raises(ClassifiedLLMError) as exc_info,
    ):
        provider.generate_image(
            prompt="x", model="openai/gpt-image-2.5-flare", size="1024x1024", n=1
        )

    assert exc_info.value.error_code == "CONTENT_POLICY"
    assert exc_info.value.is_retryable is False
    assert "safety" in exc_info.value.client_error_msg
    assert "RouterAI" in exc_info.value.client_error_msg


def test_routerai_prohibited_content_is_content_policy() -> None:
    # Seen on the stand for Gemini through RouterAI.
    provider = RouterAIImageGenerationProvider(api_key="user-key")
    body = {
        "error": {
            "message": "Провайдер заблокировал генерацию изображения (PROHIBITED_CONTENT)",
            "code": 400,
        }
    }

    with (
        patch(f"{_HTTP}.post", return_value=_response(200, body)),
        pytest.raises(ClassifiedLLMError) as exc_info,
    ):
        provider.generate_image(
            prompt="x", model="google/gemini-3.1-flash-image", size="1024x1024", n=1
        )

    assert exc_info.value.error_code == "CONTENT_POLICY"


def test_routerai_other_error_in_200_body_keeps_upstream_message() -> None:
    provider = RouterAIImageGenerationProvider(api_key="user-key")
    body = {"error": {"message": "Unsupported aspect_ratio", "code": 400}}

    with (
        patch(f"{_HTTP}.post", return_value=_response(200, body)),
        pytest.raises(ClassifiedLLMError) as exc_info,
    ):
        provider.generate_image(
            prompt="x", model="openai/gpt-image-2.5-flare", size="1024x1024", n=1
        )

    assert exc_info.value.error_code == "BAD_REQUEST"
    assert "Unsupported aspect_ratio" in exc_info.value.client_error_msg


def test_routerai_empty_data_is_an_error() -> None:
    provider = RouterAIImageGenerationProvider(api_key="user-key")

    with (
        patch(f"{_HTTP}.post", return_value=_response(200, {"data": []})),
        pytest.raises(ClassifiedLLMError),
    ):
        provider.generate_image(
            prompt="x", model="openai/gpt-image-2.5-flare", size="1024x1024", n=1
        )


# --- Polza.ai ----------------------------------------------------------------


def test_polza_generates_through_media_api_and_downloads_result() -> None:
    provider = PolzaImageGenerationProvider(api_key="user-key")
    body = {
        "id": "gen_1",
        "status": "completed",
        "data": [{"url": "https://s3.polza.ai/f/1/image.png"}],
    }

    with (
        patch(f"{_HTTP}.post", return_value=_response(200, body)) as post,
        patch(f"{_HTTP}.get", return_value=_response(200, content=PNG_BYTES)) as get,
    ):
        result = provider.generate_image(
            prompt="a blue circle",
            model="openai/gpt-image-2.5-sunburst",
            size="1024x1536",
            n=1,
            quality="low",
            response_format=None,
        )

    assert post.call_args.args[0] == "https://polza.ai/api/v1/media"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer user-key"
    assert post.call_args.kwargs["json"] == {
        "model": "openai/gpt-image-2.5-sunburst",
        "input": {"prompt": "a blue circle", "aspect_ratio": "2:3"},
        # Async: a sync GPT Image 2.5 run can outlast any HTTP read timeout
        # (seen on the stand: no answer in 180 s), so the result is polled.
        "async": True,
    }
    assert get.call_args.args[0] == "https://s3.polza.ai/f/1/image.png"
    assert _first_b64(result) == PNG_B64


def test_polza_sends_reference_images_as_base64() -> None:
    provider = PolzaImageGenerationProvider(api_key="user-key")
    body = {"id": "gen_1", "status": "completed", "data": [{"b64_json": PNG_B64}]}

    with patch(f"{_HTTP}.post", return_value=_response(200, body)) as post:
        provider.generate_image(
            prompt="make it red",
            model="google/gemini-nano-banana-2.1",
            size="1024x1024",
            n=1,
            reference_images=[ReferenceImage(data=PNG_BYTES, mime_type="image/png")],
        )

    assert post.call_args.kwargs["json"]["input"]["images"] == [
        {"type": "base64", "data": f"data:image/png;base64,{PNG_B64}"}
    ]


def test_polza_polls_until_generation_completes() -> None:
    provider = PolzaImageGenerationProvider(api_key="user-key")
    pending = {"id": "gen_7", "status": "pending"}
    processing = {"id": "gen_7", "status": "processing"}
    done = {
        "id": "gen_7",
        "status": "completed",
        "data": [{"url": "https://s3.polza.ai/f/7/image.png"}],
    }

    with (
        patch(f"{_HTTP}.post", return_value=_response(200, pending)),
        patch(
            f"{_HTTP}.get",
            side_effect=[
                _response(200, processing),
                _response(200, done),
                _response(200, content=PNG_BYTES),
            ],
        ) as get,
        patch(_POLL_SLEEP),
    ):
        result = provider.generate_image(
            prompt="x", model="openai/gpt-image-2.5-flare", size="1024x1024", n=1
        )

    status_urls = [c.args[0] for c in get.call_args_list[:2]]
    assert status_urls == ["https://polza.ai/api/v1/media/gen_7"] * 2
    assert _first_b64(result) == PNG_B64


def test_polza_polling_survives_a_transient_status_error() -> None:
    # Seen live: one status request hit a connect timeout while the paid
    # generation went on to complete. The result must not be lost.
    import requests

    provider = PolzaImageGenerationProvider(api_key="user-key")
    pending = {"id": "gen_8", "status": "pending"}
    done = {
        "id": "gen_8",
        "status": "completed",
        "data": [{"url": "https://s3.polza.ai/f/8/image.png"}],
    }

    with (
        patch(f"{_HTTP}.post", return_value=_response(200, pending)),
        patch(
            f"{_HTTP}.get",
            side_effect=[
                requests.ConnectTimeout("connect timed out"),
                _response(503, {"error": {"message": "busy"}}),
                _response(200, done),
                _response(200, content=PNG_BYTES),
            ],
        ),
        patch(_POLL_SLEEP),
    ):
        result = provider.generate_image(
            prompt="x", model="openai/gpt-image-2.5-flare", size="1024x1024", n=1
        )

    assert _first_b64(result) == PNG_B64


def test_polza_download_retries_a_transient_failure() -> None:
    # Seen live: the CDN read timed out once on a completed, paid generation.
    import requests

    provider = PolzaImageGenerationProvider(api_key="user-key")
    done = {
        "id": "gen_5",
        "status": "completed",
        "data": [{"url": "https://s3.polza.ai/f/5/image.png"}],
    }

    with (
        patch(f"{_HTTP}.post", return_value=_response(200, done)),
        patch(
            f"{_HTTP}.get",
            side_effect=[
                requests.ConnectionError("read timed out"),
                _response(502, {"error": {"message": "bad gateway"}}),
                _response(200, content=PNG_BYTES),
            ],
        ) as get,
        patch("onyx.image_gen.providers.gateway_http.time.sleep"),
    ):
        result = provider.generate_image(
            prompt="x", model="openai/gpt-image-2.5-flare", size="1024x1024", n=1
        )

    assert get.call_count == 3
    assert _first_b64(result) == PNG_B64


def test_polza_polling_stops_on_a_permanent_status_error() -> None:
    provider = PolzaImageGenerationProvider(api_key="user-key")
    pending = {"id": "gen_9", "status": "pending"}

    with (
        patch(f"{_HTTP}.post", return_value=_response(200, pending)),
        patch(
            f"{_HTTP}.get",
            return_value=_response(401, {"error": {"message": "bad key"}}),
        ),
        patch(_POLL_SLEEP),
        pytest.raises(ClassifiedLLMError) as exc_info,
    ):
        provider.generate_image(
            prompt="x", model="openai/gpt-image-2.5-flare", size="1024x1024", n=1
        )

    assert exc_info.value.error_code == "AUTH_ERROR"


def test_polza_failed_generation_raises_with_reason() -> None:
    provider = PolzaImageGenerationProvider(api_key="user-key")
    body = {
        "id": "gen_9",
        "status": "failed",
        "error": {"code": "CONTENT_POLICY", "message": "prompt rejected"},
    }

    with (
        patch(f"{_HTTP}.post", return_value=_response(200, body)),
        pytest.raises(ClassifiedLLMError) as exc_info,
    ):
        provider.generate_image(
            prompt="x", model="openai/gpt-image-2.5-flare", size="1024x1024", n=1
        )

    assert "prompt rejected" in exc_info.value.client_error_msg
    assert "Polza.ai" in exc_info.value.client_error_msg


def test_polza_refuses_non_https_result_url() -> None:
    provider = PolzaImageGenerationProvider(api_key="user-key")
    body = {
        "id": "gen_1",
        "status": "completed",
        "data": [{"url": "http://169.254.169.254/latest/meta-data"}],
    }

    with (
        patch(f"{_HTTP}.post", return_value=_response(200, body)),
        patch(f"{_HTTP}.get") as get,
        pytest.raises(ClassifiedLLMError),
    ):
        provider.generate_image(
            prompt="x", model="openai/gpt-image-2.5-flare", size="1024x1024", n=1
        )

    get.assert_not_called()


def test_polza_maps_unauthorized() -> None:
    provider = PolzaImageGenerationProvider(api_key="bad")
    body = {"error": {"code": "UNAUTHORIZED", "message": "Неверные учётные данные"}}

    with (
        patch(f"{_HTTP}.post", return_value=_response(401, body)),
        pytest.raises(ClassifiedLLMError) as exc_info,
    ):
        provider.generate_image(
            prompt="x", model="openai/gpt-image-2.5-flare", size="1024x1024", n=1
        )

    assert exc_info.value.error_code == "AUTH_ERROR"
