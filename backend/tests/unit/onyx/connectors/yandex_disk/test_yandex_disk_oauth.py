"""The Yandex Disk OAuth sign-in (cloud): the authorization address asks only
for the read rights, the code becomes the account's three token keys, and the
button works only when the app's id and secret are set."""

import time
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.yandex_disk.connector import YandexDiskConnector
from onyx.connectors.yandex_disk.source_operations import (
    ACCESS_TOKEN,
    EXPIRES_AT,
    REFRESH_TOKEN,
    YandexDiskTokenRefreshError,
    YandexDiskUnreachableError,
    exchange_code_for_token,
)

OPS = "onyx.connectors.yandex_disk.source_operations"
CONNECTOR = "onyx.connectors.yandex_disk.connector"


def _response(status_code: int = 200, body: dict[str, Any] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = body or {}
    response.text = str(body or "")
    return response


def test_the_app_id_and_secret_turn_the_button_on() -> None:
    with (
        patch(f"{CONNECTOR}.YANDEX_DISK_CLIENT_ID", "id"),
        patch(f"{CONNECTOR}.YANDEX_DISK_CLIENT_SECRET", "secret"),
    ):
        assert YandexDiskConnector.oauth_enabled()


@pytest.mark.parametrize(
    ("client_id", "client_secret"), [(None, "s"), ("i", None), ("", "")]
)
def test_without_the_app_id_or_secret_the_button_is_off(
    client_id: str | None, client_secret: str | None
) -> None:
    with (
        patch(f"{CONNECTOR}.YANDEX_DISK_CLIENT_ID", client_id),
        patch(f"{CONNECTOR}.YANDEX_DISK_CLIENT_SECRET", client_secret),
    ):
        assert not YandexDiskConnector.oauth_enabled()


def test_the_connector_takes_a_manual_token_too() -> None:
    assert YandexDiskConnector.supports_manual_credentials
    assert YandexDiskConnector.oauth_id() == DocumentSource.YANDEX_DISK


def test_the_authorization_address_asks_for_the_read_rights_only() -> None:
    with patch(f"{CONNECTOR}.YANDEX_DISK_CLIENT_ID", "app-id"):
        address = YandexDiskConnector.oauth_authorization_url(
            "https://cloud.example.com/", "state-1", {}
        )

    parts = urlsplit(address)
    query = parse_qs(parts.query)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://oauth.yandex.ru/authorize"
    )
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["app-id"]
    assert query["state"] == ["state-1"]
    assert query["redirect_uri"] == [
        "https://cloud.example.com/connector/oauth/callback/yandex_disk"
    ]
    assert query["scope"] == ["cloud_api:disk.read cloud_api:disk.info"]
    assert query["force_confirm"] == ["yes"]


def test_the_authorization_address_needs_the_app_id() -> None:
    with (
        patch(f"{CONNECTOR}.YANDEX_DISK_CLIENT_ID", None),
        pytest.raises(ValueError),
    ):
        YandexDiskConnector.oauth_authorization_url("https://x", "state", {})


def test_the_code_becomes_the_three_token_keys() -> None:
    body = {
        "access_token": "access-1",
        "refresh_token": "refresh-1",
        "expires_in": 31536000,
        "token_type": "bearer",
    }
    before = time.time()
    with (
        patch(f"{OPS}.YANDEX_DISK_CLIENT_ID", "app-id"),
        patch(f"{OPS}.YANDEX_DISK_CLIENT_SECRET", "app-secret"),
        patch(f"{OPS}.requests.post", return_value=_response(200, body)) as post,
    ):
        credentials = YandexDiskConnector.oauth_code_to_token(
            "https://cloud.example.com", "the-code", {}
        )

    assert post.call_args.args[0] == "https://oauth.yandex.ru/token"
    assert post.call_args.kwargs["data"] == {
        "grant_type": "authorization_code",
        "code": "the-code",
        "client_id": "app-id",
        "client_secret": "app-secret",
    }
    assert credentials[ACCESS_TOKEN] == "access-1"
    assert credentials[REFRESH_TOKEN] == "refresh-1"
    # The stored time is whole seconds.
    assert before + 31536000 - 1 <= credentials[EXPIRES_AT] <= time.time() + 31536000


def test_a_code_is_exchanged_once_and_not_retried() -> None:
    with (
        patch(f"{OPS}.YANDEX_DISK_CLIENT_ID", "i"),
        patch(f"{OPS}.YANDEX_DISK_CLIENT_SECRET", "s"),
        patch(
            f"{OPS}.requests.post", side_effect=requests.ConnectionError("down")
        ) as post,
        pytest.raises(YandexDiskUnreachableError),
    ):
        exchange_code_for_token("code")

    post.assert_called_once()


def test_a_refused_code_is_a_typed_error() -> None:
    refused = _response(
        400, {"error": "invalid_grant", "error_description": "Code expired"}
    )
    with (
        patch(f"{OPS}.YANDEX_DISK_CLIENT_ID", "i"),
        patch(f"{OPS}.YANDEX_DISK_CLIENT_SECRET", "s"),
        patch(f"{OPS}.requests.post", return_value=refused),
        pytest.raises(YandexDiskTokenRefreshError) as raised,
    ):
        exchange_code_for_token("old-code")

    assert raised.value.status_code == 400
    assert "invalid_grant" in str(raised.value)
