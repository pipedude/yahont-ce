"""The slim (pruning) listing of BlobStorageConnector: the ids a full run
yields, read from the object listing alone, without a download.

Pruning deletes the indexed ids that the listing does not return (feature
map: connectors §4.5), so the two id sets must match."""

from collections.abc import Iterator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector
from onyx.configs.app_configs import BLOB_STORAGE_SIZE_THRESHOLD
from onyx.configs.constants import BlobType
from onyx.connectors.blob.connector import BlobStorageConnector
from onyx.connectors.interfaces import prune_listing_honors_indexing_start
from onyx.connectors.models import (
    Document,
    ImageSection,
    SlimDocument,
    TextSection,
)

_MODIFIED = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
_BIG = BLOB_STORAGE_SIZE_THRESHOLD + 1

# key -> (listed size, content)
_BUCKET: dict[str, tuple[int, bytes]] = {
    "docs/contract.txt": (16, "Договор поставки".encode()),
    "docs/act.md": (8, "Акт № 12".encode()),
    "docs/sub/": (0, b""),
    "docs/sub/price.csv": (8, b"item,cost"),
    "docs/photo.png": (4, b"\x89PNG"),
    "docs/big-file.txt": (_BIG, b""),
    "outside/memo.txt": (4, b"memo"),
}


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def iter_chunks(self, chunk_size: int) -> Iterator[bytes]:  # noqa: ARG002
        yield self._data

    def read(self) -> bytes:
        return self._data

    def close(self) -> None:
        pass


class _FakeS3:
    """Lists keys by prefix, two objects per page, and records downloads."""

    def __init__(self, bucket: dict[str, tuple[int, bytes]]) -> None:
        self._bucket = bucket
        self.downloads: list[str] = []
        self.unreadable: set[str] = set()
        # Document links read the endpoint from the boto3 client.
        self.meta = SimpleNamespace(endpoint_url="https://s3.example.ru")

    def get_paginator(self, operation: str) -> "_FakeS3":
        assert operation == "list_objects_v2"
        return self

    def paginate(self, Bucket: str, Prefix: str) -> Iterator[dict[str, Any]]:  # noqa: N803, ARG002
        contents = [
            {"Key": key, "LastModified": _MODIFIED, "Size": size}
            for key, (size, _data) in sorted(self._bucket.items())
            if key.startswith(Prefix)
        ]
        for i in range(0, len(contents), 2):
            yield {"Contents": contents[i : i + 2]}
        # S3 answers an empty listing with a page that has no "Contents".
        yield {}

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803, ARG002
        self.downloads.append(Key)
        if Key in self.unreadable:
            raise ConnectionError("connection reset")
        return {"Body": _Body(self._bucket[Key][1])}


@pytest.fixture(autouse=True)
def no_external_services() -> Iterator[None]:
    # Text extraction reads the Unstructured key from Postgres, images and
    # tables go to the file store: none of that is under test here.
    with (
        patch(
            "onyx.file_processing.extract_file_text.get_unstructured_api_key",
            return_value=None,
        ),
        patch(
            "onyx.connectors.blob.connector.store_image_and_create_section",
            return_value=(ImageSection(image_file_id="image", link=None), "image"),
        ),
        patch(
            "onyx.connectors.blob.connector.extract_and_stage_tabular_file",
            return_value=SimpleNamespace(
                sections=[TextSection(text="item,cost", link=None)],
                staged_file_id="table",
            ),
        ),
    ):
        yield


def _connector(s3: _FakeS3, allow_images: bool) -> BlobStorageConnector:
    connector = BlobStorageConnector(
        bucket_type=BlobType.S3_COMPATIBLE.value,
        bucket_name="test-bucket",
        prefix="docs",
        endpoint_url="https://s3.example.ru",
    )
    connector.s3_client = s3  # ty: ignore[invalid-assignment]
    connector.set_allow_images(allow_images)
    connector.set_raw_file_callback(MagicMock(return_value="staged"))
    return connector


def _full_ids(connector: BlobStorageConnector) -> set[str]:
    return {
        document.id
        for batch in connector.load_from_state()
        for document in batch
        if isinstance(document, Document)
    }


def _slim_ids(connector: BlobStorageConnector) -> set[str]:
    return {
        document.id
        for batch in connector.retrieve_all_slim_docs()
        for document in batch
        if isinstance(document, SlimDocument)
    }


@pytest.mark.parametrize("allow_images", [False, True])
def test_slim_ids_match_the_full_run(allow_images: bool) -> None:
    full_ids = _full_ids(_connector(_FakeS3(_BUCKET), allow_images))
    s3 = _FakeS3(_BUCKET)

    slim_ids = _slim_ids(_connector(s3, allow_images))

    assert slim_ids == full_ids
    # Same id format as indexing: the bucket type, the bucket and the key.
    assert "BlobType.S3_COMPATIBLE:test-bucket:docs/contract.txt" in slim_ids
    assert ("BlobType.S3_COMPATIBLE:test-bucket:docs/photo.png" in slim_ids) is (
        allow_images
    )
    # Folder markers, files over the size limit and keys outside the prefix
    # are not documents.
    assert not any(
        i.endswith(("docs/sub/", "big-file.txt", "memo.txt")) for i in slim_ids
    )
    assert s3.downloads == []


def test_slim_keeps_an_object_the_full_run_could_not_read() -> None:
    # A read error skips the object in a full run; if the listing dropped it
    # too, one failed download would prune an indexed document.
    s3 = _FakeS3(_BUCKET)
    s3.unreadable = {"docs/act.md"}

    assert "BlobType.S3_COMPATIBLE:test-bucket:docs/act.md" not in _full_ids(
        _connector(s3, allow_images=False)
    )
    assert "BlobType.S3_COMPATIBLE:test-bucket:docs/act.md" in _slim_ids(
        _connector(s3, allow_images=False)
    )


def test_pruning_lists_ids_without_downloads() -> None:
    s3 = _FakeS3(_BUCKET)
    connector = _connector(s3, allow_images=False)

    result = extract_ids_from_runnable_connector(connector)

    assert set(result.raw_id_to_parent) == _slim_ids(
        _connector(_FakeS3(_BUCKET), False)
    )
    assert s3.downloads == []


def test_pruning_still_lists_every_object() -> None:
    # A full load listed every object, whatever the indexing start; the slim
    # listing keeps that behavior.
    assert prune_listing_honors_indexing_start(BlobStorageConnector) is False
