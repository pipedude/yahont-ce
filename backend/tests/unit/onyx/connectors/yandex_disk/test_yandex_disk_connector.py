"""The connector walks the folder tree from the root folder, own and shared
folders alike, skips by metadata what it cannot or must not index, and turns
each remaining file into one document. Pruning lists the same files without
downloading any."""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import quote

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import (
    Document,
    ImageSection,
    SlimDocument,
    TabularSection,
    TextSection,
)
from onyx.connectors.yandex_disk import connector as connector_module
from onyx.connectors.yandex_disk.connector import YandexDiskConnector
from onyx.connectors.yandex_disk.models import (
    DIR_TYPE,
    FILE_TYPE,
    YandexDiskFolder,
    YandexDiskInfo,
    YandexDiskResource,
)
from onyx.connectors.yandex_disk.source_operations import (
    YandexDiskAuthError,
    YandexDiskDownloadError,
    YandexDiskNotFoundError,
    YandexDiskUnavailableError,
)
from onyx.file_processing.extract_file_text import ExtractionResult

CONNECTOR = "onyx.connectors.yandex_disk.connector"
_NOW = datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc)
_OWNER = "2405471224"


def _file(
    path: str,
    *,
    owner: str = _OWNER,
    size: int = 10,
    modified: datetime = _NOW,
) -> YandexDiskResource:
    name = path.rsplit("/", 1)[-1]
    return YandexDiskResource(
        name=name,
        path=path,
        type=FILE_TYPE,
        resource_id=f"{owner}:{name}",
        created=modified - timedelta(days=1),
        modified=modified,
        size=size,
    )


def _dir(path: str, *, owner: str = _OWNER) -> YandexDiskResource:
    return YandexDiskResource(
        name=path.rsplit("/", 1)[-1],
        path=path,
        type=DIR_TYPE,
        resource_id=f"{owner}:dir:{path}",
    )


def _not_found(path: str) -> YandexDiskNotFoundError:
    return YandexDiskNotFoundError(
        f"{path} not found", status_code=404, url="https://example", body=None
    )


class _FakeDisk:
    """The gateway over an in-memory Disk: folder path to its items."""

    def __init__(self, folders: dict[str, list[YandexDiskResource]]) -> None:
        self.folders = folders
        self.file_roots: set[str] = set()
        self.folder_errors: dict[str, Exception] = {}
        self.download_errors: dict[str, Exception] = {}
        self.listed: list[tuple[str, int]] = []
        self.downloads: list[str] = []

    def get_disk_info(self) -> YandexDiskInfo:
        return YandexDiskInfo(login="owner")

    def list_folder(self, *, path: str, offset: int, limit: int) -> YandexDiskFolder:
        self.listed.append((path, offset))
        if path in self.folder_errors:
            raise self.folder_errors[path]
        if path in self.file_roots:
            return YandexDiskFolder(path=path, type=FILE_TYPE, items=[])
        if path not in self.folders:
            raise _not_found(path)
        items = self.folders[path]
        return YandexDiskFolder(
            path=path,
            type=DIR_TYPE,
            items=items[offset : offset + limit],
            total=len(items),
        )

    def download_file(self, *, path: str, max_size_bytes: int) -> bytes | None:
        self.downloads.append(path)
        if path in self.download_errors:
            raise self.download_errors[path]
        content = f"text of {path}".encode()
        return content if len(content) <= max_size_bytes else None


def _connector(disk: _FakeDisk, **kwargs: Any) -> YandexDiskConnector:
    connector = YandexDiskConnector(**kwargs)
    with patch(f"{CONNECTOR}.YandexDiskSourceOperations", return_value=disk):
        connector.load_credentials({"yandex_disk_access_token": "y0_token"})
    connector.set_allow_images(False)
    return connector


def _extract(file: Any, **_kwargs: Any) -> ExtractionResult:
    return ExtractionResult(
        text_content=file.read().decode(), embedded_images=[], metadata={}
    )


@pytest.fixture(autouse=True)
def _local_extraction() -> Iterator[None]:
    with patch(f"{CONNECTOR}.extract_text_and_images", side_effect=_extract):
        yield


def _documents(connector: YandexDiskConnector) -> list[Document]:
    return [
        item
        for batch in connector.load_from_state()
        for item in batch
        if isinstance(item, Document)
    ]


def _slim_ids(connector: YandexDiskConnector, start: float | None = None) -> set[str]:
    return {
        item.id
        for batch in connector.retrieve_all_slim_docs(start=start)
        for item in batch
        if isinstance(item, SlimDocument)
    }


def test_the_whole_disk_is_walked_from_its_root_with_subfolders() -> None:
    disk = _FakeDisk(
        {
            "disk:/": [_dir("disk:/Документы"), _file("disk:/a.txt")],
            "disk:/Документы": [_file("disk:/Документы/b.txt")],
        }
    )

    documents = _documents(_connector(disk))

    assert disk.listed[0] == ("disk:/", 0)
    assert {document.id for document in documents} == {
        f"yandex_disk:{_OWNER}:a.txt",
        f"yandex_disk:{_OWNER}:b.txt",
    }


def test_a_root_folder_walks_only_its_subtree() -> None:
    disk = _FakeDisk(
        {
            "disk:/": [_dir("disk:/Документы"), _file("disk:/a.txt")],
            "disk:/Документы": [_dir("disk:/Документы/Договоры")],
            "disk:/Документы/Договоры": [_file("disk:/Документы/Договоры/c.txt")],
        }
    )

    documents = _documents(_connector(disk, root_path="/Документы/"))

    assert {path for path, _ in disk.listed} == {
        "disk:/Документы",
        "disk:/Документы/Договоры",
    }
    assert [document.semantic_identifier for document in documents] == ["c.txt"]


def test_a_folder_is_read_page_by_page_up_to_its_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connector_module, "_FOLDER_PAGE_SIZE", 2)
    disk = _FakeDisk({"disk:/": [_file(f"disk:/{index}.txt") for index in range(5)]})

    documents = _documents(_connector(disk))

    assert disk.listed == [("disk:/", 0), ("disk:/", 2), ("disk:/", 4)]
    assert len(documents) == 5


def test_a_folder_shared_by_another_account_is_indexed() -> None:
    other = "453088635"
    disk = _FakeDisk(
        {
            "disk:/": [_dir("disk:/Общая", owner=other)],
            "disk:/Общая": [_file("disk:/Общая/план.txt", owner=other)],
        }
    )

    documents = _documents(_connector(disk))

    assert [document.id for document in documents] == [f"yandex_disk:{other}:план.txt"]


def test_a_file_listed_twice_is_indexed_once() -> None:
    twice = _file("disk:/a.txt")
    disk = _FakeDisk({"disk:/": [twice, twice]})

    documents = _documents(_connector(disk))

    assert len(documents) == 1
    assert disk.downloads == ["disk:/a.txt"]


def test_a_poll_indexes_only_files_modified_in_its_window() -> None:
    old = _file("disk:/old.txt", modified=_NOW - timedelta(days=30))
    new = _file("disk:/new.txt", modified=_NOW)
    disk = _FakeDisk({"disk:/": [old, new]})
    connector = _connector(disk)

    batches = list(
        connector.poll_source(
            (_NOW - timedelta(days=1)).timestamp(),
            (_NOW + timedelta(hours=1)).timestamp(),
        )
    )

    assert disk.downloads == ["disk:/new.txt"]
    assert [
        item.semantic_identifier
        for batch in batches
        for item in batch
        if isinstance(item, Document)
    ] == ["new.txt"]


def test_a_file_over_the_size_limit_is_skipped_before_download() -> None:
    big = _file("disk:/big.pdf", size=2 * 1024 * 1024)
    small = _file("disk:/small.txt", size=100)
    disk = _FakeDisk({"disk:/": [big, small]})

    _documents(_connector(disk, max_file_size_mb=1))

    assert disk.downloads == ["disk:/small.txt"]


def test_an_unsupported_file_is_skipped_before_download() -> None:
    disk = _FakeDisk(
        {
            "disk:/": [
                _file("disk:/план.odt"),
                _file("disk:/setup.exe"),
                _file("disk:/README"),
                _file("disk:/Договор.DOCX"),
            ]
        }
    )

    _documents(_connector(disk))

    assert disk.downloads == ["disk:/Договор.DOCX"]


def test_an_image_is_skipped_unless_images_are_allowed() -> None:
    disk = _FakeDisk({"disk:/": [_file("disk:/photo.jpg")]})
    connector = _connector(disk)

    assert _documents(connector) == []
    assert disk.downloads == []

    connector.set_allow_images(True)
    section = ImageSection(image_file_id="image-id", link="https://disk.yandex.ru")
    with patch(
        f"{CONNECTOR}.store_image_and_create_section", return_value=(section, None)
    ) as store:
        documents = _documents(connector)

    assert [document.sections for document in documents] == [[section]]
    assert store.call_args.kwargs["file_id"] == f"yandex_disk_{_OWNER}_photo.jpg"


def test_a_text_file_becomes_a_document_with_its_folder_and_link() -> None:
    report = _file("disk:/Документы/Отчёт за 2026.txt")
    disk = _FakeDisk({"disk:/": [_dir("disk:/Документы")], "disk:/Документы": [report]})

    [document] = _documents(_connector(disk))

    assert document.id == f"yandex_disk:{_OWNER}:Отчёт за 2026.txt"
    assert document.source == DocumentSource.YANDEX_DISK
    assert document.semantic_identifier == "Отчёт за 2026.txt"
    assert document.doc_updated_at == report.modified
    assert document.doc_created_at == report.created
    assert document.metadata == {"folder": "/Документы"}
    [section] = document.sections
    assert isinstance(section, TextSection)
    assert section.text == "text of disk:/Документы/Отчёт за 2026.txt"
    assert section.link == (
        f"https://disk.yandex.ru/client/disk/{quote('Документы')}"
        f"?idApp=client&dialog=slider&idDialog="
        f"{quote('/disk/Документы/Отчёт за 2026.txt', safe='')}"
    )


def test_a_file_at_the_disk_root_links_to_the_root() -> None:
    disk = _FakeDisk({"disk:/": [_file("disk:/a.txt")]})

    [document] = _documents(_connector(disk))

    assert document.metadata == {"folder": "/"}
    assert document.sections[0].link == (
        "https://disk.yandex.ru/client/disk"
        f"?idApp=client&dialog=slider&idDialog={quote('/disk/a.txt', safe='')}"
    )


def test_a_spreadsheet_becomes_tabular_sections_when_staging_is_set() -> None:
    disk = _FakeDisk({"disk:/": [_file("disk:/прайс.xlsx")]})
    connector = _connector(disk)

    assert _documents(connector) == []
    assert disk.downloads == []

    connector.set_raw_file_callback(MagicMock())
    section = TabularSection(csv_file_id="csv-id", link="https://disk.yandex.ru")
    staged = MagicMock(sections=[section], staged_file_id="staged-id")
    with patch(f"{CONNECTOR}.extract_and_stage_tabular_file", return_value=staged):
        [document] = _documents(connector)

    assert document.sections == [section]
    assert document.file_id == "staged-id"


def test_a_file_deleted_before_its_download_is_skipped() -> None:
    disk = _FakeDisk({"disk:/": [_file("disk:/gone.txt"), _file("disk:/kept.txt")]})
    disk.download_errors["disk:/gone.txt"] = _not_found("disk:/gone.txt")

    documents = _documents(_connector(disk))

    assert [document.semantic_identifier for document in documents] == ["kept.txt"]


def test_a_file_the_download_server_refuses_is_skipped_and_the_run_goes_on() -> None:
    disk = _FakeDisk({"disk:/": [_file("disk:/broken.txt"), _file("disk:/kept.txt")]})
    disk.download_errors["disk:/broken.txt"] = YandexDiskDownloadError(
        "500", status_code=500, url="https://downloader.disk.yandex.ru", body=None
    )

    documents = _documents(_connector(disk))

    assert [document.semantic_identifier for document in documents] == ["kept.txt"]


def test_a_refused_token_during_a_download_stops_the_run() -> None:
    disk = _FakeDisk({"disk:/": [_file("disk:/a.txt")]})
    disk.download_errors["disk:/a.txt"] = YandexDiskAuthError(
        "refused", status_code=401, url="https://example", body=None
    )

    with pytest.raises(YandexDiskAuthError):
        _documents(_connector(disk))


def test_a_missing_root_folder_stops_the_run() -> None:
    disk = _FakeDisk({"disk:/": []})

    with pytest.raises(ConnectorValidationError):
        _documents(_connector(disk, root_path="Нет такой"))


def test_a_root_path_that_is_a_file_stops_the_run() -> None:
    disk = _FakeDisk({})
    disk.file_roots.add("disk:/a.pdf")

    with pytest.raises(ConnectorValidationError):
        _documents(_connector(disk, root_path="a.pdf"))


def test_a_subfolder_deleted_during_the_walk_is_skipped() -> None:
    disk = _FakeDisk({"disk:/": [_dir("disk:/gone"), _file("disk:/a.txt")]})

    documents = _documents(_connector(disk))

    assert [document.semantic_identifier for document in documents] == ["a.txt"]


def test_documents_come_in_batches_of_the_batch_size() -> None:
    disk = _FakeDisk({"disk:/": [_file(f"disk:/{index}.txt") for index in range(3)]})

    batches = list(_connector(disk, batch_size=2).load_from_state())

    assert [len(batch) for batch in batches] == [2, 1]


def test_pruning_lists_the_indexed_files_without_downloading() -> None:
    disk = _FakeDisk(
        {
            "disk:/": [
                _dir("disk:/Документы"),
                _file("disk:/a.txt"),
                _file("disk:/big.pdf", size=50 * 1024 * 1024),
                _file("disk:/план.odt"),
                _file("disk:/photo.png"),
            ],
            "disk:/Документы": [_file("disk:/Документы/b.txt")],
        }
    )
    connector = _connector(disk)

    slim_ids = _slim_ids(connector)

    assert disk.downloads == []
    assert slim_ids == {f"yandex_disk:{_OWNER}:a.txt", f"yandex_disk:{_OWNER}:b.txt"}
    assert slim_ids == {document.id for document in _documents(connector)}


def test_pruning_lists_images_when_images_are_allowed() -> None:
    disk = _FakeDisk({"disk:/": [_file("disk:/photo.png")]})
    connector = _connector(disk)
    connector.set_allow_images(True)

    assert _slim_ids(connector) == {f"yandex_disk:{_OWNER}:photo.png"}


def test_pruning_honors_the_indexing_start() -> None:
    old = _file("disk:/old.txt", modified=_NOW - timedelta(days=30))
    new = _file("disk:/new.txt", modified=_NOW)
    disk = _FakeDisk({"disk:/": [old, new]})

    slim_ids = _slim_ids(_connector(disk), start=(_NOW - timedelta(days=1)).timestamp())

    assert YandexDiskConnector.slim_listing_honors_indexing_start
    assert slim_ids == {f"yandex_disk:{_OWNER}:new.txt"}


def test_pruning_stops_when_a_folder_cannot_be_read() -> None:
    disk = _FakeDisk({"disk:/": [_dir("disk:/A"), _file("disk:/a.txt")], "disk:/A": []})
    disk.folder_errors["disk:/A"] = YandexDiskUnavailableError(
        "maintenance", status_code=503, url="https://example", body=None
    )

    with pytest.raises(YandexDiskUnavailableError):
        _slim_ids(_connector(disk))


def test_pruning_stops_on_the_stop_signal() -> None:
    disk = _FakeDisk({"disk:/": [_file("disk:/a.txt")]})
    callback = MagicMock()
    callback.should_stop.return_value = True

    with pytest.raises(RuntimeError):
        list(_connector(disk).retrieve_all_slim_docs(callback=callback))
