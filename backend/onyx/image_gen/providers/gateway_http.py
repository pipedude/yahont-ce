"""HTTP helpers shared by the Russian image gateways (RouterAI, Polza.ai).

Both gateways use the tenant's own API key (BYOK), so the platform wallet and
usage limits never apply. Errors become ``ClassifiedLLMError`` so the admin key
test and the chat tool show a clear message, not a raw HTTP dump.
"""

from __future__ import annotations

import base64
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

import requests

from onyx.image_gen.interfaces import ReferenceImage
from onyx.llm.exceptions import ClassifiedLLMError

if TYPE_CHECKING:
    from onyx.image_gen.interfaces import ImageGenerationResponse

_MAX_DETAIL_CHARS = 300
_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
_DOWNLOAD_TIMEOUT_SECONDS = 60
_DOWNLOAD_ATTEMPTS = 3
_DOWNLOAD_RETRY_DELAY_SECONDS = 2

_SIZE_TO_ASPECT_RATIO = {
    "1024x1024": "1:1",
    "1536x1024": "3:2",
    "1024x1536": "2:3",
    "1792x1024": "16:9",
    "1024x1792": "9:16",
}


def aspect_ratio_for_size(size: str) -> str:
    return _SIZE_TO_ASPECT_RATIO.get(size, "1:1")


def to_data_uri(image: ReferenceImage) -> str:
    encoded = base64.b64encode(image.data).decode("ascii")
    return f"data:{image.mime_type};base64,{encoded}"


def gateway_error(
    gateway: str, message: str, error_code: str, is_retryable: bool
) -> ClassifiedLLMError:
    return ClassifiedLLMError(
        client_error_msg=f"{gateway}: {message}",
        error_code=error_code,
        is_retryable=is_retryable,
    )


def _error_detail(resp: requests.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:_MAX_DETAIL_CHARS]
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])[:_MAX_DETAIL_CHARS]
    return str(body)[:_MAX_DETAIL_CHARS]


def raise_for_status(resp: requests.Response, gateway: str) -> None:
    if resp.ok:
        return
    status = resp.status_code
    detail = _error_detail(resp)
    if status in (401, 403):
        raise gateway_error(
            gateway,
            "authentication failed. Check the API key.",
            "AUTH_ERROR",
            False,
        )
    if status == 402:
        raise gateway_error(
            gateway, f"insufficient funds. {detail}", "BUDGET_EXCEEDED", False
        )
    if status == 429:
        raise gateway_error(gateway, f"rate limit. {detail}", "RATE_LIMIT", True)
    if status >= 500:
        raise gateway_error(
            gateway, f"service error ({status}). {detail}", "SERVICE_UNAVAILABLE", True
        )
    raise gateway_error(gateway, detail, "BAD_REQUEST", False)


_CONTENT_POLICY_MARKERS = (
    "safety",
    "content policy",
    "content_policy",
    "moderation",
    "prohibited_content",
)


def _raise_for_body_error(body: dict[str, Any], gateway: str) -> None:
    """Both gateways can answer HTTP 200 with an ``error`` body.

    RouterAI does so when the upstream safety system refuses the prompt (for
    example, a brand name); Polza does so for a failed generation.
    """
    error = body.get("error")
    if not error:
        return
    if isinstance(error, dict):
        detail = str(error.get("message") or error)[:_MAX_DETAIL_CHARS]
        code = str(error.get("code") or "")
    else:
        detail = str(error)[:_MAX_DETAIL_CHARS]
        code = ""
    if any(marker in f"{detail} {code}".lower() for marker in _CONTENT_POLICY_MARKERS):
        raise gateway_error(
            gateway,
            "the request was rejected by the content safety filter. "
            f"Rephrase the prompt (for example, without brand names). {detail}",
            "CONTENT_POLICY",
            False,
        )
    raise gateway_error(gateway, detail, "BAD_REQUEST", False)


def _json_body(resp: requests.Response, gateway: str) -> dict[str, Any]:
    try:
        body = resp.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise gateway_error(gateway, "unexpected response format.", "API_ERROR", True)
    _raise_for_body_error(body, gateway)
    return body


def _request(
    method: str,
    url: str,
    api_key: str,
    gateway: str,
    timeout_seconds: int,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        if method == "POST":
            resp = requests.post(
                url, headers=headers, json=payload, timeout=timeout_seconds
            )
        else:
            resp = requests.get(url, headers=headers, timeout=timeout_seconds)
    except requests.Timeout:
        raise gateway_error(gateway, "the request timed out.", "CONNECTION_ERROR", True)
    except requests.RequestException as e:
        raise gateway_error(
            gateway,
            f"connection failed ({type(e).__name__}).",
            "CONNECTION_ERROR",
            True,
        )
    raise_for_status(resp, gateway)
    return _json_body(resp, gateway)


def post_json(
    url: str,
    api_key: str,
    payload: dict[str, Any],
    gateway: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    return _request("POST", url, api_key, gateway, timeout_seconds, payload)


def get_json(
    url: str, api_key: str, gateway: str, timeout_seconds: int
) -> dict[str, Any]:
    return _request("GET", url, api_key, gateway, timeout_seconds)


def _download_once(url: str, gateway: str) -> bytes:
    try:
        resp = requests.get(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise gateway_error(
            gateway,
            f"could not download the image ({type(e).__name__}).",
            "CONNECTION_ERROR",
            True,
        )
    raise_for_status(resp, gateway)
    return resp.content


def _download_as_b64(url: str, gateway: str) -> str:
    # The URL comes from the gateway response: only public https is fetched.
    if not url.startswith("https://"):
        raise gateway_error(gateway, "the result URL is not https.", "API_ERROR", False)
    # The generation is already paid for; a download is free to repeat.
    content = b""
    for attempt in range(1, _DOWNLOAD_ATTEMPTS + 1):
        try:
            content = _download_once(url, gateway)
            break
        except ClassifiedLLMError as e:
            if not e.is_retryable or attempt == _DOWNLOAD_ATTEMPTS:
                raise
            time.sleep(_DOWNLOAD_RETRY_DELAY_SECONDS * attempt)
    if len(content) > _MAX_DOWNLOAD_BYTES:
        raise gateway_error(gateway, "the image is too large.", "API_ERROR", False)
    return base64.b64encode(content).decode("ascii")


def build_image_response(
    items: Any, prompt: str, gateway: str
) -> ImageGenerationResponse:
    """Turn ``data`` items (``b64_json`` or ``url``) into an ImageResponse."""
    from litellm.types.utils import ImageObject, ImageResponse

    images: list[ImageObject] = []
    for item in items if isinstance(items, list) else [items]:
        if not isinstance(item, dict):
            continue
        b64 = item.get("b64_json")
        if not b64 and item.get("url"):
            b64 = _download_as_b64(str(item["url"]), gateway)
        if b64:
            images.append(ImageObject(b64_json=b64, revised_prompt=prompt))

    if not images:
        raise gateway_error(gateway, "no image returned.", "API_ERROR", True)
    return ImageResponse(created=int(datetime.now().timestamp()), data=images)
