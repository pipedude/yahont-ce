"""Each Yandex Disk check maps the gateway's answer onto a validation outcome:
a refused token, a root folder that is missing or is a file, or an API that
does not answer. Blocking validation runs the same helpers."""

from typing import Any
from unittest.mock import MagicMock, create_autospec, patch

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
)
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InconclusiveValidationError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
    UnexpectedValidationError,
    UnreachableValidationError,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.yandex_disk.capability_checks import (
    FOLDER_CHECK_ID,
    TOKEN_CHECK_ID,
    build_yandex_disk_indexing_checks,
)
from onyx.connectors.yandex_disk.connector import YandexDiskConnector
from onyx.connectors.yandex_disk.models import (
    DIR_TYPE,
    FILE_TYPE,
    YandexDiskFolder,
    YandexDiskInfo,
)
from onyx.connectors.yandex_disk.source_operations import (
    YandexDiskApiError,
    YandexDiskAuthError,
    YandexDiskForbiddenError,
    YandexDiskNotFoundError,
    YandexDiskRateLimitError,
    YandexDiskSourceOperations,
    YandexDiskTokenLockError,
    YandexDiskTokenRefreshError,
    YandexDiskUnavailableError,
    YandexDiskUnreachableError,
)


def _api_error(error_class: type[YandexDiskApiError], status: int) -> Exception:
    return error_class("refused", status_code=status, url="https://example", body=None)


def _check(check_id: str) -> CapabilityCheck:
    return next(
        check
        for check in build_yandex_disk_indexing_checks()
        if check.check_id == check_id
    )


def _ops() -> MagicMock:
    ops = create_autospec(YandexDiskSourceOperations, instance=True)
    ops.credentials_provider = MagicMock()
    ops.credentials_provider.get_credentials.return_value = {
        "yandex_disk_access_token": "y0_token"
    }
    ops.get_disk_info.return_value = YandexDiskInfo(login="owner")
    ops.list_folder.return_value = YandexDiskFolder(
        path="disk:/Документы", type=DIR_TYPE, items=[], total=0
    )
    return ops


def _context(
    ops: MagicMock, config: dict[str, Any] | None = None
) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.YANDEX_DISK,
        credential_json={},
        connector_specific_config=config,
        source_operations=ops,
    )


def test_the_source_registers_named_checks() -> None:
    check_ids = {
        check.check_id for check in get_capability_checks(DocumentSource.YANDEX_DISK)
    }

    assert {TOKEN_CHECK_ID, FOLDER_CHECK_ID} <= check_ids


def test_the_token_check_names_the_account() -> None:
    output = _check(TOKEN_CHECK_ID).run(_context(_ops()))

    assert output is not None and output.summary == "Signed in as owner"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_api_error(YandexDiskAuthError, 401), CredentialInvalidError),
        (ConnectorMissingCredentialError("Yandex Disk"), CredentialInvalidError),
        (_api_error(YandexDiskForbiddenError, 403), InsufficientPermissionsError),
        (_api_error(YandexDiskRateLimitError, 429), RateLimitedValidationError),
        (_api_error(YandexDiskUnavailableError, 503), UnreachableValidationError),
        (
            YandexDiskUnreachableError("slow", timed_out=True),
            UnreachableValidationError,
        ),
        (_api_error(YandexDiskApiError, 400), UnexpectedValidationError),
    ],
)
def test_the_token_check_maps_each_failure(
    error: Exception, expected: type[Exception]
) -> None:
    ops = _ops()
    ops.get_disk_info.side_effect = error

    with pytest.raises(expected):
        _check(TOKEN_CHECK_ID).run(_context(ops))


def _credential_context(
    ops: MagicMock, credential_json: dict[str, Any]
) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.YANDEX_DISK,
        credential_json=credential_json,
        source_operations=ops,
    )


def test_a_refused_refresh_asks_to_reconnect() -> None:
    ops = _ops()
    ops.get_disk_info.side_effect = YandexDiskTokenRefreshError(
        "invalid_grant", status_code=400, url="https://oauth.yandex.ru/token", body=None
    )

    with pytest.raises(CredentialExpiredError) as raised:
        _check(TOKEN_CHECK_ID).run(
            _credential_context(
                ops, {"yandex_disk_access_token": "a", "yandex_disk_refresh_token": "r"}
            )
        )

    assert "Reconnect" in (raised.value.description or "")


def test_a_busy_refresh_lock_is_inconclusive() -> None:
    ops = _ops()
    ops.get_disk_info.side_effect = YandexDiskTokenLockError("busy")

    with pytest.raises(InconclusiveValidationError):
        _check(TOKEN_CHECK_ID).run(_context(ops))


def test_a_refused_oauth_token_asks_to_reconnect_and_a_manual_one_to_reissue() -> None:
    refused = _api_error(YandexDiskAuthError, 401)
    oauth_ops, manual_ops = _ops(), _ops()
    oauth_ops.get_disk_info.side_effect = refused
    manual_ops.get_disk_info.side_effect = refused

    with pytest.raises(CredentialInvalidError) as oauth:
        _check(TOKEN_CHECK_ID).run(
            _credential_context(
                oauth_ops,
                {
                    "yandex_disk_access_token": "a",
                    "yandex_disk_refresh_token": "r",
                },
            )
        )
    with pytest.raises(CredentialInvalidError) as manual:
        _check(TOKEN_CHECK_ID).run(
            _credential_context(manual_ops, {"yandex_disk_access_token": "a"})
        )

    assert "Reconnect" in (oauth.value.description or "")
    assert "Reconnect" not in (manual.value.description or "")
    assert "new OAuth token" in (manual.value.description or "")


def test_the_folder_check_reads_the_configured_folder() -> None:
    ops = _ops()

    output = _check(FOLDER_CHECK_ID).run(_context(ops, {"root_path": "/Документы/"}))

    assert output is not None and output.summary == "Found folder /Документы"
    assert ops.list_folder.call_args.kwargs["path"] == "disk:/Документы"


def test_the_folder_check_reads_the_disk_root_without_a_folder() -> None:
    ops = _ops()

    output = _check(FOLDER_CHECK_ID).run(_context(ops, {"root_path": ""}))

    assert output is not None and output.summary == "Read the whole Disk"
    assert ops.list_folder.call_args.kwargs["path"] == "disk:/"


def test_the_folder_check_fails_for_a_missing_folder() -> None:
    ops = _ops()
    ops.list_folder.side_effect = _api_error(YandexDiskNotFoundError, 404)

    with pytest.raises(ConnectorValidationError) as raised:
        _check(FOLDER_CHECK_ID).run(_context(ops, {"root_path": "Нет такой"}))

    assert raised.value.summary == "Folder not found"
    assert "/Нет такой" in str(raised.value)


def test_the_folder_check_fails_for_a_file() -> None:
    ops = _ops()
    ops.list_folder.return_value = YandexDiskFolder(
        path="disk:/a.pdf", type=FILE_TYPE, items=[]
    )

    with pytest.raises(ConnectorValidationError) as raised:
        _check(FOLDER_CHECK_ID).run(_context(ops, {"root_path": "a.pdf"}))

    assert raised.value.summary == "Path is a file"


def _connector(ops: MagicMock, root_path: str = "") -> YandexDiskConnector:
    connector = YandexDiskConnector(root_path=root_path)
    with patch(
        "onyx.connectors.yandex_disk.connector.YandexDiskSourceOperations",
        return_value=ops,
    ):
        connector.load_credentials({"yandex_disk_access_token": "y0_token"})
    return connector


def test_validation_passes_for_a_token_and_an_existing_folder() -> None:
    ops = _ops()

    _connector(ops, "Документы").validate_connector_settings()

    ops.get_disk_info.assert_called_once()
    assert ops.list_folder.call_args.kwargs["path"] == "disk:/Документы"


def test_validation_rejects_a_refused_token() -> None:
    ops = _ops()
    ops.get_disk_info.side_effect = _api_error(YandexDiskAuthError, 401)

    with pytest.raises(CredentialInvalidError):
        _connector(ops).validate_connector_settings()


def test_validation_rejects_a_missing_folder() -> None:
    ops = _ops()
    ops.list_folder.side_effect = _api_error(YandexDiskNotFoundError, 404)

    with pytest.raises(ConnectorValidationError):
        _connector(ops, "Нет такой").validate_connector_settings()


def test_validation_does_not_pause_when_the_api_does_not_answer() -> None:
    ops = _ops()
    ops.get_disk_info.side_effect = YandexDiskUnreachableError(
        str(requests.ConnectionError("down")), timed_out=False
    )

    with pytest.raises(UnexpectedValidationError):
        _connector(ops).validate_connector_settings()
