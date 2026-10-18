import base64
import io
import json
import wave
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from openai import AuthenticationError

from onyx.db.models import VoiceProvider
from onyx.voice.factory import get_voice_provider
from onyx.voice.providers.gateway import (
    GatewayStreamingSynthesizer,
    GatewayVoiceProvider,
    PolzaVoiceProvider,
    RouterAIVoiceProvider,
)

MP3_FRAME = b"\xff\xf3\xc4\xc4" + b"\x00" * 60
# ID3v2.4 header with a 5-byte body (syncsafe size), then the body itself.
ID3_TAG = b"ID3\x04\x00\x00\x00\x00\x00\x05" + b"TAG42"


class FakeSpeechResponse:
    def __init__(self, content_type: str, chunks: list[bytes]) -> None:
        self.headers = {"content-type": content_type}
        self._chunks = chunks

    async def read(self) -> bytes:
        return b"".join(self._chunks)

    async def iter_bytes(self, chunk_size: int = 8192) -> AsyncIterator[bytes]:  # noqa: ARG002
        for chunk in self._chunks:
            yield chunk


class FakeSpeechStream:
    def __init__(self, response: FakeSpeechResponse, calls: list[dict[str, Any]]):
        self._response = response
        self._calls = calls

    def create(self, **kwargs: Any) -> "FakeSpeechStream":
        self._calls.append(kwargs)
        return self

    async def __aenter__(self) -> FakeSpeechResponse:
        return self._response

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeTranscriptions:
    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self._calls = calls

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self._calls.append(kwargs)
        return SimpleNamespace(text="привет")


class FakeClient:
    def __init__(
        self,
        speech: FakeSpeechResponse | None = None,
        get_error: Exception | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.get_paths: list[str] = []
        self._get_error = get_error
        self.audio = SimpleNamespace(
            speech=SimpleNamespace(
                with_streaming_response=FakeSpeechStream(
                    speech or FakeSpeechResponse("audio/mpeg", []), self.calls
                )
            ),
            transcriptions=FakeTranscriptions(self.calls),
        )

    async def get(self, path: str, **_: Any) -> None:
        self.get_paths.append(path)
        if self._get_error is not None:
            raise self._get_error


def _with_client(
    provider: GatewayVoiceProvider, client: FakeClient
) -> GatewayVoiceProvider:
    provider._client = cast(Any, client)
    return provider


async def _collect(stream: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in stream])


# --- Factory and catalog ---


@pytest.mark.parametrize(
    "provider_type, cls, stt, tts, voice, api_base",
    [
        (
            "routerai",
            RouterAIVoiceProvider,
            "elevenlabs/scribe-v2",
            "elevenlabs/eleven-v4",
            "george",
            "https://routerai.ru/api/v1",
        ),
        (
            "polza",
            PolzaVoiceProvider,
            "openai/gpt-4o-transcribe",
            "openai/tts-1",
            "alloy",
            "https://polza.ai/api/v1",
        ),
    ],
)
def test_factory_builds_gateway_with_defaults(
    provider_type: str,
    cls: type[GatewayVoiceProvider],
    stt: str,
    tts: str,
    voice: str,
    api_base: str,
) -> None:
    row = VoiceProvider(name="x", provider_type=provider_type)
    row.api_key = "key"  # ty: ignore[invalid-assignment]

    provider = get_voice_provider(row)

    assert isinstance(provider, cls)
    assert provider.stt_model == stt
    assert provider.tts_model == tts
    assert provider.default_voice == voice
    assert provider.api_base == api_base


def test_gateway_tts_models_match_owner_choice() -> None:
    assert [
        m["id"] for m in RouterAIVoiceProvider(None).get_available_tts_models()
    ] == [
        "elevenlabs/eleven-v4",
        "elevenlabs/eleven-v4-turbo",
    ]
    assert [m["id"] for m in PolzaVoiceProvider(None).get_available_tts_models()] == [
        "openai/tts-1",
        "openai/tts-1-hd",
    ]


def test_gateway_capabilities() -> None:
    for provider in (RouterAIVoiceProvider("k"), PolzaVoiceProvider("k")):
        # No Realtime WS on the gateways: STT goes through the chunked HTTP path.
        assert not provider.supports_streaming_stt()
        assert provider.supports_streaming_tts()
        # The tenant key goes only to the gateway's own host.
        assert not provider.supports_target_uri()


def test_get_available_voices_returns_copy() -> None:
    provider = PolzaVoiceProvider("k")
    provider.get_available_voices().clear()
    assert "coral" in [v["id"] for v in provider.get_available_voices()]


# --- Speech synthesis ---


@pytest.mark.asyncio
async def test_polza_json_speech_is_decoded() -> None:
    body = json.dumps(
        {"audio": base64.b64encode(MP3_FRAME).decode(), "contentType": "audio/mpeg"}
    ).encode()
    client = FakeClient(
        speech=FakeSpeechResponse("application/json; charset=utf-8", [body])
    )
    provider = _with_client(PolzaVoiceProvider("k"), client)

    audio = await _collect(provider.synthesize_stream("Привет", voice="nova"))

    assert audio == MP3_FRAME
    assert client.calls[0]["model"] == "openai/tts-1"
    assert client.calls[0]["voice"] == "nova"
    assert client.calls[0]["response_format"] == "mp3"


@pytest.mark.asyncio
async def test_json_speech_without_audio_raises() -> None:
    body = json.dumps({"error": {"message": "no money"}}).encode()
    client = FakeClient(speech=FakeSpeechResponse("application/json", [body]))
    provider = _with_client(PolzaVoiceProvider("k"), client)

    with pytest.raises(RuntimeError, match="no money"):
        await _collect(provider.synthesize_stream("Привет"))


@pytest.mark.asyncio
async def test_binary_speech_drops_leading_id3_tag_split_across_chunks() -> None:
    stream = ID3_TAG + MP3_FRAME
    chunks = [stream[:4], stream[4:12], stream[12:]]
    client = FakeClient(speech=FakeSpeechResponse("audio/mpeg", chunks))
    provider = _with_client(RouterAIVoiceProvider("k"), client)

    audio = await _collect(provider.synthesize_stream("Привет"))

    assert audio == MP3_FRAME
    assert client.calls[0]["voice"] == "george"


@pytest.mark.asyncio
async def test_binary_speech_without_tag_is_unchanged() -> None:
    client = FakeClient(
        speech=FakeSpeechResponse("audio/mpeg", [MP3_FRAME[:3], MP3_FRAME[3:]])
    )
    provider = _with_client(RouterAIVoiceProvider("k"), client)

    assert await _collect(provider.synthesize_stream("Привет")) == MP3_FRAME


@pytest.mark.asyncio
async def test_streaming_synthesizer_queues_gateway_audio() -> None:
    client = FakeClient(speech=FakeSpeechResponse("audio/mpeg", [ID3_TAG + MP3_FRAME]))
    provider = _with_client(RouterAIVoiceProvider("k"), client)

    synthesizer = await provider.create_streaming_synthesizer(voice="sarah", speed=1.5)
    assert isinstance(synthesizer, GatewayStreamingSynthesizer)
    await synthesizer.send_text("Первое предложение.")
    await synthesizer.flush()

    audio = b""
    while (chunk := await synthesizer.receive_audio()) is not None:
        audio += chunk
    await synthesizer.close()

    assert audio == MP3_FRAME
    assert client.calls[0]["voice"] == "sarah"
    assert client.calls[0]["speed"] == 1.5


# --- Speech recognition ---


@pytest.mark.asyncio
async def test_transcribe_wraps_pcm16_as_wav() -> None:
    client = FakeClient()
    provider = _with_client(RouterAIVoiceProvider("k"), client)

    text = await provider.transcribe(b"\x00\x00" * 240, "pcm16")

    assert text == "привет"
    call = client.calls[0]
    assert call["model"] == "elevenlabs/scribe-v2"
    assert call["file"].name == "audio.wav"
    with wave.open(io.BytesIO(call["file"].getvalue()), "rb") as wav_file:
        assert wav_file.getframerate() == 24000
        assert wav_file.getnframes() == 240


# --- Key check ---


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cls, path", [(RouterAIVoiceProvider, "/key"), (PolzaVoiceProvider, "/balance")]
)
async def test_validate_credentials_calls_authenticated_endpoint(
    cls: type[GatewayVoiceProvider], path: str
) -> None:
    client = FakeClient()
    provider = _with_client(cls("k"), client)

    await provider.validate_credentials()

    assert client.get_paths == [path]


@pytest.mark.asyncio
async def test_validate_credentials_rejects_bad_key() -> None:
    request = httpx.Request("GET", "https://polza.ai/api/v1/balance")
    error = AuthenticationError(
        "bad key", response=httpx.Response(401, request=request), body=None
    )
    provider = _with_client(PolzaVoiceProvider("k"), FakeClient(get_error=error))

    with pytest.raises(RuntimeError, match="Invalid Polza.ai API key"):
        await provider.validate_credentials()
