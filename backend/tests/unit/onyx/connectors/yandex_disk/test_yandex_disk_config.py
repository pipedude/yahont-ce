"""The root folder is one folder of the Disk, however the admin types it: a
deeper folder narrows the scope, a shallower one widens it. A larger size
limit widens the scope too."""

from typing import Any

import pytest
from pydantic import ValidationError

from onyx.configs.constants import DocumentSource
from onyx.connectors.config_diff import classify_config_change, source_change_override
from onyx.connectors.field_policy import ScopeDirection
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.connectors.yandex_disk.config import (
    YandexDiskConnectorConfig,
    normalize_root_path,
    root_api_path,
)


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("", ""),
        ("/", ""),
        ("  ", ""),
        ("Документы", "Документы"),
        (" /Документы/Договоры/ ", "Документы/Договоры"),
        ("disk:/Документы/Договоры", "Документы/Договоры"),
        ("Документы//Договоры", "Документы/Договоры"),
        ("Отчёты 2026 (итог)", "Отчёты 2026 (итог)"),
    ],
)
def test_the_root_path_is_one_folder_however_it_is_typed(
    typed: str, expected: str
) -> None:
    assert normalize_root_path(typed) == expected


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("https://disk.yandex.ru/client/disk/testing", "testing"),
        (
            "https://disk.yandex.ru/client/disk/%D0%94%D0%BE%D0%BA%D1%83%D0%BC%D0%B5%D0%BD%D1%82%D1%8B",
            "Документы",
        ),
        (
            "https://disk.yandex.ru/client/disk/Документы/Договоры?idApp=client&dialog=slider",
            "Документы/Договоры",
        ),
        (" https://disk.yandex.ru/client/disk/testing/ ", "testing"),
        ("https://disk.360.yandex.ru/client/disk/testing", "testing"),
        ("https://disk.yandex.ru/client/disk", ""),
        ("https://disk.yandex.ru/client/disk/", ""),
    ],
)
def test_a_folder_address_from_the_browser_gives_its_path(
    typed: str, expected: str
) -> None:
    assert normalize_root_path(typed) == expected


def test_an_address_off_the_disk_web_app_is_not_read_as_a_path() -> None:
    assert normalize_root_path("https://example.com/client/disk/testing") == (
        "https:/example.com/client/disk/testing"
    )


def test_the_api_path_of_the_whole_disk_is_its_root() -> None:
    assert root_api_path("") == "disk:/"
    assert root_api_path("/Документы/") == "disk:/Документы"


def test_the_size_limit_is_at_least_one_megabyte() -> None:
    with pytest.raises(ValidationError):
        YandexDiskConnectorConfig(max_file_size_mb=0)


def _directions(
    old: dict[str, Any], new: dict[str, Any]
) -> dict[str, ScopeDirection | None]:
    source = DocumentSource.YANDEX_DISK
    changes = classify_config_change(
        CONNECTOR_CLASS_MAP[source].config_class,
        old,
        new,
        source_change_override(source, old, new),
    )
    return {change.field_name: change.scope_direction for change in changes}


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ({"root_path": ""}, {"root_path": "Документы"}, ScopeDirection.NARROW),
        (
            {"root_path": "Документы"},
            {"root_path": "Документы/Договоры"},
            ScopeDirection.NARROW,
        ),
        (
            {"root_path": "Документы/Договоры"},
            {"root_path": "Документы"},
            ScopeDirection.WIDEN,
        ),
        ({"root_path": "Документы"}, {"root_path": ""}, ScopeDirection.WIDEN),
        # "Документы2" is not inside "Документы": the two hold other files.
        ({"root_path": "Документы"}, {"root_path": "Документы2"}, ScopeDirection.BOTH),
        ({"root_path": "Документы"}, {"root_path": "Фото"}, ScopeDirection.BOTH),
    ],
)
def test_a_root_folder_change_has_a_direction(
    old: dict[str, Any], new: dict[str, Any], expected: ScopeDirection
) -> None:
    assert _directions(old, new) == {"root_path": expected}


def test_the_same_folder_typed_another_way_is_no_change() -> None:
    assert _directions({"root_path": "Документы"}, {"root_path": "/Документы/"}) == {}


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (20, 50, ScopeDirection.WIDEN),
        (50, 10, ScopeDirection.NARROW),
    ],
)
def test_a_size_limit_change_has_a_direction(
    old: int, new: int, expected: ScopeDirection
) -> None:
    assert _directions({"max_file_size_mb": old}, {"max_file_size_mb": new}) == {
        "max_file_size_mb": expected
    }
