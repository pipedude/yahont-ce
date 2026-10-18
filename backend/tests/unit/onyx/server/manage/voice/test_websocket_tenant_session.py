"""The voice WebSockets must read the provider row from the tenant's schema.

A bare `Session(engine)` queries the default schema, where `voice_provider`
does not exist in a multi-tenant deployment ("relation voice_provider does not
exist"). The REST routes use `get_session_with_current_tenant`; so must these.
"""

from collections.abc import Callable, Coroutine
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocket

from onyx.db.models import User
from onyx.server.manage.voice import websocket_api


class _TenantSession:
    def __init__(self, opened: list[str]) -> None:
        self._opened = opened

    def __enter__(self) -> "_TenantSession":
        self._opened.append("tenant")
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent_json: list[dict[str, str]] = []
        self.accept = AsyncMock()
        self.close = AsyncMock()

    async def send_json(self, payload: dict[str, str]) -> None:
        self.sent_json.append(payload)


def _use_tenant_session(monkeypatch: pytest.MonkeyPatch, fetch_name: str) -> list[str]:
    opened: list[str] = []
    monkeypatch.setattr(
        websocket_api, "get_session_with_current_tenant", lambda: _TenantSession(opened)
    )
    monkeypatch.setattr(websocket_api, fetch_name, lambda _db_session: None)
    return opened


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler, fetch_name, message",
    [
        (
            websocket_api.websocket_transcribe,
            "fetch_default_stt_provider",
            "No speech-to-text provider configured",
        ),
        (
            websocket_api.websocket_synthesize,
            "fetch_default_tts_provider",
            "No text-to-speech provider configured",
        ),
    ],
)
async def test_websocket_reads_provider_in_tenant_session(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[..., Coroutine[Any, Any, None]],
    fetch_name: str,
    message: str,
) -> None:
    opened = _use_tenant_session(monkeypatch, fetch_name)
    websocket = _FakeWebSocket()

    await handler(
        cast(WebSocket, websocket),
        _user=cast(User, SimpleNamespace(id="user-7")),
    )

    assert opened == ["tenant"]
    assert websocket.sent_json == [{"type": "error", "message": message}]
