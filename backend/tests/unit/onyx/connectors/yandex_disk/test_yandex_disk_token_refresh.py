"""The gateway refreshes an expiring OAuth token under the provider's lock and
writes both tokens back, since Yandex rotates the refresh token. A manual
token never refreshes."""

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.connectors.yandex_disk.source_operations import (
    ACCESS_TOKEN,
    EXPIRES_AT,
    REFRESH_TOKEN,
    YandexDiskSourceOperations,
    YandexDiskTokenLockError,
    YandexDiskTokenRefreshError,
    YandexDiskUnreachableError,
    is_expiring,
    refresh_oauth_token,
)

OPS = "onyx.connectors.yandex_disk.source_operations"


def _provider(credentials: dict[str, Any]) -> MagicMock:
    provider = MagicMock()
    provider.get_credentials.return_value = credentials
    provider.__enter__.return_value = provider
    return provider


def _expiring() -> dict[str, Any]:
    return {
        ACCESS_TOKEN: "old",
        REFRESH_TOKEN: "r1",
        EXPIRES_AT: int(time.time()) + 60,
    }


def _fresh() -> dict[str, Any]:
    return {
        ACCESS_TOKEN: "new",
        REFRESH_TOKEN: "r2",
        EXPIRES_AT: int(time.time()) + 3600,
    }


def _response(status_code: int, body: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = body
    response.text = str(body)
    return response


def test_a_token_far_from_expiry_is_used_as_is() -> None:
    credentials = {**_fresh()}
    provider = _provider(credentials)
    ops = YandexDiskSourceOperations(credentials_provider=provider)

    assert ops._authorization() == "OAuth new"

    provider.__enter__.assert_not_called()


def test_a_manual_token_is_never_refreshed() -> None:
    provider = _provider({ACCESS_TOKEN: "manual"})
    ops = YandexDiskSourceOperations(credentials_provider=provider)

    assert ops._authorization() == "OAuth manual"

    provider.__enter__.assert_not_called()
    provider.set_credentials.assert_not_called()


def test_an_expiring_token_without_a_refresh_token_is_used_as_is() -> None:
    provider = _provider({ACCESS_TOKEN: "t", EXPIRES_AT: int(time.time()) + 10})
    ops = YandexDiskSourceOperations(credentials_provider=provider)

    assert ops._authorization() == "OAuth t"
    assert not is_expiring(provider.get_credentials())


@patch(f"{OPS}.refresh_oauth_token")
def test_an_expiring_token_is_refreshed_under_the_lock_and_written_back(
    refresh: MagicMock,
) -> None:
    expiring, fresh = _expiring(), _fresh()
    refresh.return_value = fresh
    provider = _provider(expiring)
    ops = YandexDiskSourceOperations(credentials_provider=provider)

    assert ops._authorization() == "OAuth new"

    provider.__enter__.assert_called_once()
    refresh.assert_called_once_with(expiring)
    provider.set_credentials.assert_called_once_with(fresh)
    assert ops._authorization() == "OAuth new"
    assert refresh.call_count == 1


@patch(f"{OPS}.refresh_oauth_token")
def test_a_token_another_task_already_refreshed_is_reused(refresh: MagicMock) -> None:
    provider = _provider(_expiring())
    # The second read, under the lock, sees the other task's refresh.
    provider.get_credentials.side_effect = [_expiring(), _fresh()]
    ops = YandexDiskSourceOperations(credentials_provider=provider)

    assert ops._authorization() == "OAuth new"

    refresh.assert_not_called()
    provider.set_credentials.assert_not_called()


def test_a_busy_lock_is_a_typed_error() -> None:
    provider = _provider(_expiring())
    provider.__enter__.side_effect = RuntimeError("lock busy")
    ops = YandexDiskSourceOperations(credentials_provider=provider)

    with pytest.raises(YandexDiskTokenLockError):
        ops._authorization()


@patch(f"{OPS}.refresh_oauth_token")
def test_a_refused_refresh_is_not_written_back(refresh: MagicMock) -> None:
    refresh.side_effect = YandexDiskTokenRefreshError(
        "invalid_grant", status_code=400, url="https://oauth.yandex.ru/token", body=None
    )
    provider = _provider(_expiring())
    ops = YandexDiskSourceOperations(credentials_provider=provider)

    with pytest.raises(YandexDiskTokenRefreshError):
        ops._authorization()

    provider.set_credentials.assert_not_called()


def test_a_refresh_sends_the_app_credentials_and_keeps_the_rotated_token() -> None:
    body = {"access_token": "a2", "refresh_token": "r2", "expires_in": 3600}
    before = time.time()
    with (
        patch(f"{OPS}.YANDEX_DISK_CLIENT_ID", "app-id"),
        patch(f"{OPS}.YANDEX_DISK_CLIENT_SECRET", "app-secret"),
        patch(f"{OPS}.requests.post", return_value=_response(200, body)) as post,
    ):
        refreshed = refresh_oauth_token({ACCESS_TOKEN: "a1", REFRESH_TOKEN: "r1"})

    assert post.call_args.args[0] == "https://oauth.yandex.ru/token"
    assert post.call_args.kwargs["data"] == {
        "grant_type": "refresh_token",
        "refresh_token": "r1",
        "client_id": "app-id",
        "client_secret": "app-secret",
    }
    assert refreshed[ACCESS_TOKEN] == "a2"
    assert refreshed[REFRESH_TOKEN] == "r2"
    # The stored time is whole seconds.
    assert before + 3600 - 1 <= refreshed[EXPIRES_AT] <= time.time() + 3600


def test_a_refresh_without_a_new_refresh_token_keeps_the_stored_one() -> None:
    body = {"access_token": "a2", "expires_in": 3600}
    with (
        patch(f"{OPS}.YANDEX_DISK_CLIENT_ID", "i"),
        patch(f"{OPS}.YANDEX_DISK_CLIENT_SECRET", "s"),
        patch(f"{OPS}.requests.post", return_value=_response(200, body)),
    ):
        refreshed = refresh_oauth_token({ACCESS_TOKEN: "a1", REFRESH_TOKEN: "r1"})

    assert refreshed[REFRESH_TOKEN] == "r1"


@pytest.mark.parametrize("error", ["invalid_grant", "invalid_client"])
def test_a_refused_refresh_token_is_a_typed_error_and_not_retried(error: str) -> None:
    refused = _response(400, {"error": error, "error_description": "no"})
    with (
        patch(f"{OPS}.YANDEX_DISK_CLIENT_ID", "i"),
        patch(f"{OPS}.YANDEX_DISK_CLIENT_SECRET", "s"),
        patch(f"{OPS}.requests.post", return_value=refused) as post,
        patch(f"{OPS}.time.sleep"),
        pytest.raises(YandexDiskTokenRefreshError) as raised,
    ):
        refresh_oauth_token({ACCESS_TOKEN: "a", REFRESH_TOKEN: "r"})

    post.assert_called_once()
    assert raised.value.status_code == 400
    assert error in str(raised.value)


def test_a_refresh_retries_a_dead_connection_and_a_server_fault() -> None:
    body = {"access_token": "a2", "refresh_token": "r2", "expires_in": 60}
    answers = [
        requests.ConnectionError("down"),
        _response(503, {}),
        _response(200, body),
    ]
    with (
        patch(f"{OPS}.YANDEX_DISK_CLIENT_ID", "i"),
        patch(f"{OPS}.YANDEX_DISK_CLIENT_SECRET", "s"),
        patch(f"{OPS}.requests.post", side_effect=answers) as post,
        patch(f"{OPS}.time.sleep"),
    ):
        refreshed = refresh_oauth_token({ACCESS_TOKEN: "a", REFRESH_TOKEN: "r"})

    assert post.call_count == 3
    assert refreshed[ACCESS_TOKEN] == "a2"


def test_a_refresh_retries_a_read_timeout() -> None:
    """A lost answer is lost either way; the retry wins when the first
    request was never processed."""
    body = {"access_token": "a2", "refresh_token": "r2", "expires_in": 60}
    answers = [requests.ReadTimeout("slow"), _response(200, body)]
    with (
        patch(f"{OPS}.YANDEX_DISK_CLIENT_ID", "i"),
        patch(f"{OPS}.YANDEX_DISK_CLIENT_SECRET", "s"),
        patch(f"{OPS}.requests.post", side_effect=answers) as post,
        patch(f"{OPS}.time.sleep"),
    ):
        refreshed = refresh_oauth_token({ACCESS_TOKEN: "a", REFRESH_TOKEN: "r"})

    assert post.call_count == 2
    assert refreshed[REFRESH_TOKEN] == "r2"


def test_a_refresh_gives_up_after_its_attempts() -> None:
    with (
        patch(f"{OPS}.YANDEX_DISK_CLIENT_ID", "i"),
        patch(f"{OPS}.YANDEX_DISK_CLIENT_SECRET", "s"),
        patch(f"{OPS}.requests.post", side_effect=requests.ReadTimeout("slow")) as post,
        patch(f"{OPS}.time.sleep"),
        pytest.raises(YandexDiskUnreachableError) as raised,
    ):
        refresh_oauth_token({ACCESS_TOKEN: "a", REFRESH_TOKEN: "r"})

    assert post.call_count == 3
    assert raised.value.timed_out


def test_an_answer_without_a_token_is_a_typed_error() -> None:
    with (
        patch(f"{OPS}.YANDEX_DISK_CLIENT_ID", "i"),
        patch(f"{OPS}.YANDEX_DISK_CLIENT_SECRET", "s"),
        patch(f"{OPS}.requests.post", return_value=_response(200, {})),
        pytest.raises(YandexDiskTokenRefreshError) as raised,
    ):
        refresh_oauth_token({ACCESS_TOKEN: "a", REFRESH_TOKEN: "r"})

    assert raised.value.status_code == 200


def test_a_refresh_without_the_app_id_is_a_typed_error() -> None:
    with (
        patch(f"{OPS}.YANDEX_DISK_CLIENT_ID", None),
        patch(f"{OPS}.YANDEX_DISK_CLIENT_SECRET", None),
        patch(f"{OPS}.requests.post") as post,
        pytest.raises(YandexDiskTokenRefreshError),
    ):
        refresh_oauth_token({ACCESS_TOKEN: "a", REFRESH_TOKEN: "r"})

    post.assert_not_called()
