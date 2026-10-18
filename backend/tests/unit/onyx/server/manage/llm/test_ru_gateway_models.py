"""Model fetchers for the RouterAI and Polza.ai gateways.

The payloads are trimmed copies of the gateways' real `/models` responses,
plus entries that must be filtered out (media models, embeddings).
"""

from typing import cast
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.llm.api import (
    get_polza_available_models,
    get_routerai_available_models,
)
from onyx.server.manage.llm.ru_gateways import GatewayModelsRequest

_ROUTERAI_SAMPLE = {
    "data": [
        {
            "id": "qwen/qwen3-next-80b-a3b-thinking",
            "name": "Qwen: Qwen3 Next 80B A3B Thinking",
            "context_length": 262144,
            "architecture": {
                "modality": "text->text",
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["max_tokens", "reasoning", "include_reasoning"],
        },
        {
            "id": "anthropic/claude-sonnet-4.5",
            "name": "Anthropic: Claude Sonnet 4.5",
            "context_length": 1000000,
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["max_tokens", "tools"],
        },
        {
            "id": "alibaba/happyhorse-1.0",
            "name": "Alibaba: HappyHorse 1.0",
            "context_length": 0,
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["video"],
            },
        },
        {
            "id": "openai/text-embedding-3-large",
            "name": "OpenAI: Text Embedding 3 Large",
            "context_length": 8191,
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["embeddings"],
            },
        },
        {
            # no context and no capability metadata at all
            "id": "vendor/plain-chat",
            "name": "Plain Chat",
            "architecture": {},
        },
    ]
}

_POLZA_SAMPLE = {
    "data": [
        {
            "id": "openai/gpt-6.1-sol",
            "name": "OpenAI: GPT-6.1 Sol",
            "type": "chat",
            "architecture": {
                "modality": "text+image+file->text",
                "input_modalities": ["file", "image", "text"],
                "output_modalities": ["text"],
            },
            "top_provider": {
                "context_length": 1050000,
                "max_completion_tokens": 128000,
                "supported_parameters": ["reasoning", "tools", "tool_choice"],
            },
        },
        {
            "id": "deepseek/deepseek-v4-flash",
            "name": "DeepSeek: DeepSeek V4 Flash",
            "type": "chat",
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "top_provider": {
                "context_length": 131072,
                "supported_parameters": ["tools"],
            },
        },
        {
            "id": "google/imagen-5",
            "name": "Google: Imagen 5",
            "type": "image",
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["image"],
            },
            "top_provider": {"context_length": 4096},
        },
        {
            # speech-to-text: answers in text but is not a chat model
            "id": "openai/whisper-large",
            "name": "OpenAI: Whisper Large",
            "type": "stt",
            "architecture": {
                "input_modalities": ["audio"],
                "output_modalities": ["text"],
            },
            "top_provider": {"context_length": 4096},
        },
        {
            "id": "baai/bge-m3",
            "name": "BAAI: BGE M3",
            "type": "embedding",
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["embeddings"],
            },
            "top_provider": {"context_length": 8192},
        },
    ]
}


def _fetch_routerai(sample: dict | None = None) -> dict:
    with (
        patch("onyx.server.manage.llm.api._resolve_api_key", return_value="k"),
        patch(
            "onyx.server.manage.llm.api._get_openai_compatible_models_response",
            return_value=sample if sample is not None else _ROUTERAI_SAMPLE,
        ),
    ):
        results = get_routerai_available_models(
            request=GatewayModelsRequest(api_key="k"),
            _=cast(User, None),
            db_session=cast(Session, None),
        )
    return {r.name: r for r in results}


def _fetch_polza(sample: dict | None = None) -> tuple[dict, dict]:
    with (
        patch("onyx.server.manage.llm.api._resolve_api_key", return_value=None),
        patch(
            "onyx.server.manage.llm.api._get_openai_compatible_models_response",
            return_value=sample if sample is not None else _POLZA_SAMPLE,
        ) as fetch,
    ):
        results = get_polza_available_models(
            request=GatewayModelsRequest(),
            _=cast(User, None),
            db_session=cast(Session, None),
        )
    return {r.name: r for r in results}, dict(fetch.call_args.kwargs)


def test_routerai_keeps_only_text_chat_models() -> None:
    by_name = _fetch_routerai()

    assert sorted(by_name) == [
        "anthropic/claude-sonnet-4.5",
        "qwen/qwen3-next-80b-a3b-thinking",
        "vendor/plain-chat",
    ]


def test_routerai_maps_context_vision_and_reasoning() -> None:
    by_name = _fetch_routerai()

    qwen = by_name["qwen/qwen3-next-80b-a3b-thinking"]
    assert qwen.max_input_tokens == 262144
    assert qwen.supports_reasoning is True
    assert qwen.supports_image_input is False
    claude = by_name["anthropic/claude-sonnet-4.5"]
    assert claude.supports_image_input is True
    assert claude.supports_reasoning is False


def test_routerai_strips_the_vendor_prefix_from_display_names() -> None:
    by_name = _fetch_routerai()

    assert by_name["qwen/qwen3-next-80b-a3b-thinking"].display_name == (
        "Qwen3 Next 80B A3B Thinking"
    )
    assert by_name["vendor/plain-chat"].display_name == "Plain Chat"


def test_routerai_treats_missing_context_as_unknown() -> None:
    assert _fetch_routerai()["vendor/plain-chat"].max_input_tokens is None


def test_routerai_requests_the_models_url_under_its_default_base() -> None:
    with (
        patch("onyx.server.manage.llm.api._resolve_api_key", return_value="k"),
        patch(
            "onyx.server.manage.llm.api._get_openai_compatible_models_response",
            return_value=_ROUTERAI_SAMPLE,
        ) as fetch,
    ):
        get_routerai_available_models(
            request=GatewayModelsRequest(api_key="k"),
            _=cast(User, None),
            db_session=cast(Session, None),
        )

    assert fetch.call_args.kwargs["url"] == "https://routerai.ru/api/v1/models"
    assert fetch.call_args.kwargs["api_key"] == "k"


@pytest.mark.parametrize(
    "api_base,expected_url",
    [
        ("", "https://routerai.ru/api/v1/models"),
        ("   ", "https://routerai.ru/api/v1/models"),
        ("https://proxy.example/api/v1/", "https://proxy.example/api/v1/models"),
        ("https://proxy.example/api", "https://proxy.example/api/v1/models"),
    ],
)
def test_routerai_base_url_is_normalized_and_blank_means_default(
    api_base: str, expected_url: str
) -> None:
    with (
        patch("onyx.server.manage.llm.api._resolve_api_key", return_value="k"),
        patch(
            "onyx.server.manage.llm.api._get_openai_compatible_models_response",
            return_value=_ROUTERAI_SAMPLE,
        ) as fetch,
    ):
        get_routerai_available_models(
            request=GatewayModelsRequest(api_base=api_base, api_key="k"),
            _=cast(User, None),
            db_session=cast(Session, None),
        )

    assert fetch.call_args.kwargs["url"] == expected_url


def test_polza_keeps_only_chat_models_with_text_output() -> None:
    by_name, _ = _fetch_polza()

    assert sorted(by_name) == ["deepseek/deepseek-v4-flash", "openai/gpt-6.1-sol"]


def test_polza_reads_context_and_reasoning_from_top_provider() -> None:
    by_name, _ = _fetch_polza()

    gpt = by_name["openai/gpt-6.1-sol"]
    assert gpt.max_input_tokens == 1050000
    assert gpt.supports_reasoning is True
    assert gpt.supports_image_input is True
    deepseek = by_name["deepseek/deepseek-v4-flash"]
    assert deepseek.max_input_tokens == 131072
    assert deepseek.supports_reasoning is False
    assert deepseek.supports_image_input is False


def test_polza_asks_the_gateway_for_chat_models_only() -> None:
    _, kwargs = _fetch_polza()

    assert kwargs["url"] == "https://polza.ai/api/v1/models?type=chat"
    # The Polza catalog is public: no key is required to list it.
    assert kwargs["api_key"] is None


def test_polza_strips_the_vendor_prefix_from_display_names() -> None:
    by_name, _ = _fetch_polza()

    assert by_name["openai/gpt-6.1-sol"].display_name == "GPT-6.1 Sol"


@pytest.mark.parametrize("fetch", [_fetch_routerai, _fetch_polza])
def test_an_empty_catalog_is_a_validation_error(fetch) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(OnyxError):
        fetch({"data": []})


@pytest.mark.parametrize("fetch", [_fetch_routerai, _fetch_polza])
def test_a_catalog_without_chat_models_is_a_validation_error(fetch) -> None:  # type: ignore[no-untyped-def]
    media_only = {
        "data": [
            {
                "id": "x/video",
                "name": "Video",
                "type": "video",
                "architecture": {"output_modalities": ["video"]},
            }
        ]
    }

    with pytest.raises(OnyxError):
        fetch(media_only)
