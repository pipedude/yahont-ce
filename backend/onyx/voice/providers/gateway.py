"""Russian voice gateways (RouterAI, Polza.ai), tenant key only (BYOK).

Both gateways are OpenAI-compatible (`/audio/transcriptions`, `/audio/speech`)
under their own model ids, so the platform wallet and limits never apply.
Neither has a Realtime WebSocket: STT uses the chunked HTTP path. RouterAI
streams binary MP3; Polza answers speech with JSON (`audio` in base64).
"""

import base64
import io
import json
from collections.abc import AsyncIterator
from typing import ClassVar

import httpx

from onyx.llm.well_known_providers.constants import (
    POLZA_DEFAULT_API_BASE,
    ROUTERAI_DEFAULT_API_BASE,
)
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call
from onyx.voice.audio_utils import pcm16_to_wav
from onyx.voice.providers.openai import OpenAIStreamingSynthesizer, OpenAIVoiceProvider

_CHUNK_BYTES = 8192
_ID3_HEADER_BYTES = 10
_ID3_FOOTER_FLAG = 0x10
_MAX_DETAIL_CHARS = 300


def _id3v2_size(head: bytes) -> int | None:
    """Length of a leading ID3v2 tag: 0 if none, None if more bytes are needed."""
    if len(head) < _ID3_HEADER_BYTES:
        return None if b"ID3".startswith(head[:3]) else 0
    if head[:3] != b"ID3":
        return 0
    # The body size is a 28-bit "syncsafe" integer: 7 bits per byte.
    body = 0
    for byte in head[6:10]:
        body = body * 128 + (byte & 0x7F)
    size = _ID3_HEADER_BYTES + body
    if head[5] & _ID3_FOOTER_FLAG:
        size += _ID3_HEADER_BYTES
    return size


async def _without_id3v2(chunks: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Drop a leading ID3v2 tag.

    Every sentence is a separate MP3 file appended to one MediaSource buffer,
    so a tag would sit between audio frames.
    """
    head = b""
    passthrough = False
    async for chunk in chunks:
        if passthrough:
            yield chunk
            continue
        head += chunk
        size = _id3v2_size(head)
        if size is None or len(head) < size:
            continue
        passthrough = True
        if head[size:]:
            yield head[size:]
    if not passthrough and head:
        yield head


def _decode_json_audio(body: bytes, gateway: str) -> bytes:
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    audio = data.get("audio") if isinstance(data, dict) else None
    if isinstance(audio, str) and audio:
        return base64.b64decode(audio)
    error = data.get("error") if isinstance(data, dict) else None
    detail = error.get("message") if isinstance(error, dict) else error or body
    raise RuntimeError(
        f"{gateway}: no audio returned. {str(detail)[:_MAX_DETAIL_CHARS]}"
    )


class GatewayStreamingSynthesizer(OpenAIStreamingSynthesizer):
    """Sentence-by-sentence TTS over the gateway's own speech call."""

    def __init__(self, provider: "GatewayVoiceProvider", voice: str, speed: float):
        super().__init__(
            api_key=provider.api_key or "",
            voice=voice,
            model=provider.tts_model,
            speed=speed,
            api_base=provider.api_base,
        )
        self._provider = provider

    async def _synthesize_text(self, text: str) -> None:
        if self._closed:
            return
        try:
            async for chunk in self._provider.synthesize_stream(
                text, self.voice, self.speed
            ):
                if self._closed:
                    break
                if chunk:
                    await self._audio_queue.put(chunk)
        except Exception as e:
            self._logger.error(
                "%s streaming synthesis error: %s", self._provider.GATEWAY, e
            )


class GatewayVoiceProvider(OpenAIVoiceProvider):
    """Shared behavior; each gateway sets its catalog and key-check endpoint."""

    GATEWAY: ClassVar[str]
    PROVIDER_TYPE: ClassVar[str]
    DEFAULT_API_BASE: ClassVar[str]
    # Authenticated GET: `/models` answers 200 even for a wrong key.
    KEY_CHECK_PATH: ClassVar[str]
    STT_MODELS: ClassVar[list[dict[str, str]]]
    TTS_MODELS: ClassVar[list[dict[str, str]]]
    VOICES: ClassVar[list[dict[str, str]]]

    def __init__(
        self,
        api_key: str | None,
        api_base: str | None = None,
        stt_model: str | None = None,
        tts_model: str | None = None,
        default_voice: str | None = None,
    ):
        super().__init__(
            api_key=api_key,
            api_base=api_base or self.DEFAULT_API_BASE,
            stt_model=stt_model or self.STT_MODELS[0]["id"],
            tts_model=tts_model or self.TTS_MODELS[0]["id"],
            default_voice=default_voice or self.VOICES[0]["id"],
        )

    async def transcribe(self, audio_data: bytes, audio_format: str) -> str:
        if audio_format == "pcm16":
            audio_data = pcm16_to_wav(audio_data)
            audio_format = "wav"
        audio_file = io.BytesIO(audio_data)
        audio_file.name = f"audio.{audio_format}"

        with traced_llm_call(
            flow=LLMFlow.STT, model=self.stt_model, provider=self.PROVIDER_TYPE
        ):
            response = await self._get_client().audio.transcriptions.create(
                model=self.stt_model, file=audio_file
            )
        return response.text

    async def synthesize_stream(
        self, text: str, voice: str | None = None, speed: float = 1.0
    ) -> AsyncIterator[bytes]:
        with traced_llm_call(
            flow=LLMFlow.TTS,
            model=self.tts_model,
            provider=self.PROVIDER_TYPE,
            input_messages=[{"role": "user", "content": text}],
        ):
            async with self._get_client().audio.speech.with_streaming_response.create(
                model=self.tts_model,
                voice=voice or self.default_voice,
                input=text,
                speed=max(0.25, min(4.0, speed)),
                response_format="mp3",
            ) as response:
                if response.headers.get("content-type", "").startswith(
                    "application/json"
                ):
                    audio = _decode_json_audio(await response.read(), self.GATEWAY)
                    yield audio[_id3v2_size(audio) or 0 :]
                    return
                async for chunk in _without_id3v2(response.iter_bytes(_CHUNK_BYTES)):
                    yield chunk

    async def validate_credentials(self) -> None:
        from openai import AuthenticationError, PermissionDeniedError

        try:
            await self._get_client().get(
                f"/{self.KEY_CHECK_PATH}", cast_to=httpx.Response
            )
        except (AuthenticationError, PermissionDeniedError):
            raise RuntimeError(f"Invalid {self.GATEWAY} API key.")

    def get_available_voices(self) -> list[dict[str, str]]:
        return self.VOICES.copy()

    def get_available_stt_models(self) -> list[dict[str, str]]:
        return self.STT_MODELS.copy()

    def get_available_tts_models(self) -> list[dict[str, str]]:
        return self.TTS_MODELS.copy()

    def supports_streaming_stt(self) -> bool:
        return False

    def supports_target_uri(self) -> bool:
        return False

    async def create_streaming_synthesizer(
        self, voice: str | None = None, speed: float = 1.0
    ) -> GatewayStreamingSynthesizer:
        if not self.api_key:
            raise ValueError("API key required for streaming TTS")
        synthesizer = GatewayStreamingSynthesizer(
            self, voice or self.default_voice, speed
        )
        await synthesizer.connect()
        return synthesizer


class RouterAIVoiceProvider(GatewayVoiceProvider):
    GATEWAY = "RouterAI"
    PROVIDER_TYPE = "routerai"
    DEFAULT_API_BASE = ROUTERAI_DEFAULT_API_BASE
    KEY_CHECK_PATH = "key"
    STT_MODELS = [{"id": "elevenlabs/scribe-v2", "name": "ElevenLabs Scribe v2"}]
    TTS_MODELS = [
        {"id": "elevenlabs/eleven-v4", "name": "Eleven v4"},
        {"id": "elevenlabs/eleven-v4-turbo", "name": "Eleven v4 Turbo"},
    ]
    VOICES = [
        {"id": voice, "name": voice.capitalize()}
        for voice in (
            "george",
            "sarah",
            "adam",
            "alice",
            "bella",
            "bill",
            "brian",
            "callum",
            "charlie",
            "chris",
            "daniel",
            "eric",
            "harry",
            "jessica",
            "laura",
            "liam",
            "lily",
            "matilda",
            "river",
            "roger",
            "will",
        )
    ]


class PolzaVoiceProvider(GatewayVoiceProvider):
    GATEWAY = "Polza.ai"
    PROVIDER_TYPE = "polza"
    DEFAULT_API_BASE = POLZA_DEFAULT_API_BASE
    KEY_CHECK_PATH = "balance"
    STT_MODELS = [{"id": "openai/gpt-4o-transcribe", "name": "GPT-4o Transcribe"}]
    TTS_MODELS = [
        {"id": "openai/tts-1", "name": "TTS-1"},
        {"id": "openai/tts-1-hd", "name": "TTS-1 HD"},
    ]
    # The voices Polza accepts for tts-1 and tts-1-hd.
    VOICES = [
        {"id": voice, "name": voice.capitalize()}
        for voice in (
            "alloy",
            "ash",
            "coral",
            "echo",
            "fable",
            "nova",
            "onyx",
            "sage",
            "shimmer",
        )
    ]
