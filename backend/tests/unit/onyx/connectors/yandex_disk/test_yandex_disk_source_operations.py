"""The gateway sends the token as an OAuth header, retries what a wait can
pass, turns every other refusal into a typed error, and downloads only from
Yandex hosts."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.yandex_disk.models import DIR_TYPE, FILE_TYPE
from onyx.connectors.yandex_disk.source_operations import (
    YandexDiskApiError,
    YandexDiskAuthError,
    YandexDiskDownloadError,
    YandexDiskForbiddenError,
    YandexDiskNotFoundError,
    YandexDiskRateLimitError,
    YandexDiskSourceOperations,
    YandexDiskUnavailableError,
    YandexDiskUnexpectedLinkError,
    YandexDiskUnreachableError,
)

OPS = "onyx.connectors.yandex_disk.source_operations"


def _ops(credentials: dict[str, Any] | None = None) -> YandexDiskSourceOperations:
    return YandexDiskSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None,
            "yandex_disk",
            credentials
            if credentials is not None
            else {"yandex_disk_access_token": "y0_token"},
        )
    )


def _response(
    status_code: int,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = body or {}
    response.text = str(body or "")
    response.headers = headers or {}
    return response


def test_the_token_is_sent_as_an_oauth_header() -> None:
    with patch(
        f"{OPS}.requests.get",
        return_value=_response(200, {"user": {"login": "owner"}}),
    ) as get:
        info = _ops().get_disk_info()

    assert info.login == "owner"
    assert get.call_args.kwargs["headers"]["Authorization"] == "OAuth y0_token"


def test_a_connection_that_hangs_fails_within_the_connect_timeout() -> None:
    with patch(
        f"{OPS}.requests.get",
        return_value=_response(200, {"user": {"login": "owner"}}),
    ) as get:
        _ops().get_disk_info()

    connect_timeout, read_timeout = get.call_args.kwargs["timeout"]
    assert connect_timeout <= 10
    assert read_timeout >= 60


def test_a_credential_without_a_token_is_missing() -> None:
    with pytest.raises(ConnectorMissingCredentialError):
        _ops({}).get_disk_info()


def test_a_folder_page_lists_its_items_and_total() -> None:
    body = {
        "type": DIR_TYPE,
        "path": "disk:/Документы",
        "_embedded": {
            "total": 2,
            "items": [
                {
                    "name": "Договоры",
                    "path": "disk:/Документы/Договоры",
                    "type": DIR_TYPE,
                    "resource_id": "1:dir",
                },
                {
                    "name": "Отчёт.pdf",
                    "path": "disk:/Документы/Отчёт.pdf",
                    "type": FILE_TYPE,
                    "resource_id": "1:file",
                    "modified": "2026-10-31T09:17:35+00:00",
                    "created": "2026-10-30T09:17:35+00:00",
                    "size": 8280325,
                    "mime_type": "application/pdf",
                },
            ],
        },
    }
    with patch(f"{OPS}.requests.get", return_value=_response(200, body)) as get:
        folder = _ops().list_folder(path="disk:/Документы", offset=0, limit=1000)

    params = get.call_args.kwargs["params"]
    assert params["path"] == "disk:/Документы"
    assert params["offset"] == 0
    assert params["limit"] == 1000
    assert folder.type == DIR_TYPE
    assert folder.total == 2
    assert [item.name for item in folder.items] == ["Договоры", "Отчёт.pdf"]
    report = folder.items[1]
    assert report.resource_id == "1:file"
    assert report.size == 8280325
    assert report.modified is not None and report.modified.tzinfo is not None


def test_a_file_path_lists_no_items() -> None:
    body = {"type": FILE_TYPE, "path": "disk:/a.pdf"}
    with patch(f"{OPS}.requests.get", return_value=_response(200, body)):
        folder = _ops().list_folder(path="disk:/a.pdf", offset=0, limit=1)

    assert folder.type == FILE_TYPE
    assert folder.items == []


@pytest.mark.parametrize(
    ("status_code", "error_class"),
    [
        (401, YandexDiskAuthError),
        (403, YandexDiskForbiddenError),
        (404, YandexDiskNotFoundError),
        (400, YandexDiskApiError),
    ],
)
def test_a_refusal_is_a_typed_error_and_not_retried(
    status_code: int, error_class: type[Exception]
) -> None:
    with (
        patch(f"{OPS}.requests.get", return_value=_response(status_code)) as get,
        patch(f"{OPS}.time.sleep"),
        pytest.raises(error_class),
    ):
        _ops().get_disk_info()

    get.assert_called_once()


def test_a_rate_limit_waits_as_told_and_retries() -> None:
    responses = [
        _response(429, headers={"Retry-After": "3"}),
        _response(200, {"user": {"login": "owner"}}),
    ]
    with (
        patch(f"{OPS}.requests.get", side_effect=responses) as get,
        patch(f"{OPS}.time.sleep") as sleep,
    ):
        info = _ops().get_disk_info()

    assert info.login == "owner"
    assert get.call_count == 2
    assert 3 in [call.args[0] for call in sleep.call_args_list]


def test_a_rate_limit_that_does_not_pass_is_a_typed_error() -> None:
    with (
        patch(f"{OPS}.requests.get", return_value=_response(429)),
        patch(f"{OPS}.time.sleep"),
        pytest.raises(YandexDiskRateLimitError),
    ):
        _ops().get_disk_info()


@pytest.mark.parametrize("status_code", [423, 503])
def test_maintenance_that_does_not_end_is_a_typed_error(status_code: int) -> None:
    with (
        patch(f"{OPS}.requests.get", return_value=_response(status_code)) as get,
        patch(f"{OPS}.time.sleep"),
        pytest.raises(YandexDiskUnavailableError),
    ):
        _ops().get_disk_info()

    assert get.call_count > 1


def test_no_answer_after_retries_is_a_typed_error() -> None:
    with (
        patch(f"{OPS}.requests.get", side_effect=requests.ReadTimeout("slow")) as get,
        patch(f"{OPS}.time.sleep"),
        pytest.raises(YandexDiskUnreachableError) as raised,
    ):
        _ops().get_disk_info()

    assert get.call_count > 1
    assert raised.value.timed_out


def test_a_file_downloads_from_its_link_with_the_token() -> None:
    link = {"href": "https://downloader.disk.yandex.ru/disk/abc?uid=1", "method": "GET"}
    with (
        patch(f"{OPS}.requests.get", return_value=_response(200, link)) as get,
        patch(f"{OPS}.fetch_url", return_value=b"body") as download,
    ):
        content = _ops().download_file(path="disk:/a.txt", max_size_bytes=100)

    assert content == b"body"
    assert get.call_args.kwargs["params"]["path"] == "disk:/a.txt"
    download.assert_called_once()
    assert download.call_args.args[0] == link["href"]
    assert download.call_args.kwargs["max_size_bytes"] == 100
    assert download.call_args.kwargs["headers"] == {"Authorization": "OAuth y0_token"}


@pytest.mark.parametrize(
    "href",
    [
        "https://evil.example.com/disk/abc",
        "http://downloader.disk.yandex.ru/disk/abc",
        "https://yandex.ru.evil.example.com/disk/abc",
    ],
)
def test_a_link_off_yandex_hosts_is_not_downloaded(href: str) -> None:
    with (
        patch(f"{OPS}.requests.get", return_value=_response(200, {"href": href})),
        patch(f"{OPS}.fetch_url") as download,
        pytest.raises(YandexDiskUnexpectedLinkError),
    ):
        _ops().download_file(path="disk:/a.txt", max_size_bytes=100)

    download.assert_not_called()


def test_a_download_server_fault_is_retried_with_a_new_link() -> None:
    links = [
        _response(200, {"href": "https://downloader.disk.yandex.ru/disk/first"}),
        _response(200, {"href": "https://downloader.disk.yandex.ru/disk/second"}),
    ]
    fault = requests.HTTPError(response=_response(500))
    with (
        patch(f"{OPS}.requests.get", side_effect=links) as get,
        patch(f"{OPS}.fetch_url", side_effect=[fault, b"body"]) as download,
        patch(f"{OPS}.time.sleep"),
    ):
        content = _ops().download_file(path="disk:/a.jpg", max_size_bytes=100)

    assert content == b"body"
    assert get.call_count == 2
    assert [call.args[0] for call in download.call_args_list] == [
        "https://downloader.disk.yandex.ru/disk/first",
        "https://downloader.disk.yandex.ru/disk/second",
    ]


def test_a_download_server_fault_that_does_not_pass_is_a_download_error() -> None:
    link = {"href": "https://downloader.disk.yandex.ru/disk/abc"}
    fault = requests.HTTPError(response=_response(500))
    with (
        patch(f"{OPS}.requests.get", return_value=_response(200, link)),
        patch(f"{OPS}.fetch_url", side_effect=fault) as download,
        patch(f"{OPS}.time.sleep"),
        pytest.raises(YandexDiskDownloadError) as raised,
    ):
        _ops().download_file(path="disk:/a.jpg", max_size_bytes=100)

    assert download.call_count == 3
    assert raised.value.status_code == 500


def test_a_download_refusal_is_a_download_error_and_not_retried() -> None:
    link = {"href": "https://downloader.disk.yandex.ru/disk/abc"}
    refused = requests.HTTPError(response=_response(403))
    with (
        patch(f"{OPS}.requests.get", return_value=_response(200, link)),
        patch(f"{OPS}.fetch_url", side_effect=refused) as download,
        pytest.raises(YandexDiskDownloadError) as raised,
    ):
        _ops().download_file(path="disk:/a.jpg", max_size_bytes=100)

    download.assert_called_once()
    assert raised.value.status_code == 403


def test_a_dead_connection_during_a_download_is_retried() -> None:
    link = {"href": "https://downloader.disk.yandex.ru/disk/abc"}
    with (
        patch(f"{OPS}.requests.get", return_value=_response(200, link)),
        patch(
            f"{OPS}.fetch_url", side_effect=[requests.ConnectionError("reset"), b"ok"]
        ) as download,
        patch(f"{OPS}.time.sleep"),
    ):
        content = _ops().download_file(path="disk:/a.jpg", max_size_bytes=100)

    assert content == b"ok"
    assert download.call_count == 2


def test_a_file_deleted_before_its_download_is_not_found() -> None:
    link = {"href": "https://downloader.disk.yandex.ru/disk/abc"}
    gone = requests.HTTPError(response=_response(404))
    with (
        patch(f"{OPS}.requests.get", return_value=_response(200, link)),
        patch(f"{OPS}.fetch_url", side_effect=gone),
        pytest.raises(YandexDiskNotFoundError),
    ):
        _ops().download_file(path="disk:/a.txt", max_size_bytes=100)
