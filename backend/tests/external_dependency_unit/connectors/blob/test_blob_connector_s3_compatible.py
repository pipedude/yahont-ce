"""BlobStorageConnector against a real S3 API server (the stack's own
SeaweedFS `object-store`, which — like the Russian providers this mode
targets — is S3-compatible but is not AWS/GCS/OCI).

The compose service only runs with the `s3-filestore` profile; start it
before this test (the stand runs with FILE_STORE_BACKEND=postgres)."""

import uuid
from collections.abc import Iterator
from io import BytesIO
from unittest.mock import MagicMock, patch

import boto3
import pytest

from onyx.configs.app_configs import S3_ENDPOINT_URL
from onyx.configs.constants import BlobType, DocumentSource
from onyx.connectors.blob.connector import BlobStorageConnector
from onyx.connectors.models import Document
from onyx.server.security.models import SSRFProtectionLevel

if not S3_ENDPOINT_URL:
    pytest.skip("Needs S3_ENDPOINT_URL", allow_module_level=True)

_ACCESS_KEY = "minioadmin"
_SECRET_KEY = "minioadmin"


@pytest.fixture
def bucket_name() -> Iterator[str]:
    name = f"s3-compatible-test-{uuid.uuid4().hex[:12]}"
    client = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
        region_name="us-east-1",
    )
    client.create_bucket(Bucket=name)
    client.put_object(
        Bucket=name,
        Key="reports/invoice.txt",
        Body=BytesIO("Счёт № 145 на оплату".encode()),
    )
    yield name
    objects = client.list_objects_v2(Bucket=name).get("Contents", [])
    for obj in objects:
        client.delete_object(Bucket=name, Key=obj["Key"])
    client.delete_bucket(Bucket=name)


def _make_connector(bucket_name: str) -> BlobStorageConnector:
    connector = BlobStorageConnector(
        bucket_type=BlobType.S3_COMPATIBLE.value,
        bucket_name=bucket_name,
        endpoint_url=S3_ENDPOINT_URL,
        region_name=None,
    )
    # The test reaches the server on the host's loopback (127.0.0.1:9004).
    # ALLOW_PRIVATE_NETWORK lets a LAN host through but keeps loopback blocked;
    # only DISABLED allows loopback (cloud metadata stays blocked at every
    # level). Inside the stack the server is `http://object-store:8333`, a
    # private address that ALLOW_PRIVATE_NETWORK is enough for.
    with patch(
        "onyx.connectors.blob.connector.get_security_settings",
        return_value=MagicMock(ssrf_protection_level=SSRFProtectionLevel.DISABLED),
    ):
        connector.load_credentials(
            {"access_key_id": _ACCESS_KEY, "secret_access_key": _SECRET_KEY}
        )
    return connector


def test_validate_connector_settings_succeeds(bucket_name: str) -> None:
    _make_connector(bucket_name).validate_connector_settings()


@pytest.fixture
def no_unstructured_api_key() -> Iterator[None]:
    # Text extraction first reads the Unstructured API key from the key-value
    # store (Postgres), which this test does not initialize and which is not
    # what is under test. Same patch as tests/daily/connectors/conftest.py.
    with patch(
        "onyx.file_processing.extract_file_text.get_unstructured_api_key",
        return_value=None,
    ):
        yield


@pytest.mark.usefixtures("no_unstructured_api_key")
def test_the_uploaded_file_is_indexed_with_the_right_source(
    bucket_name: str,
) -> None:
    connector = _make_connector(bucket_name)

    documents = [
        document
        for batch in connector.load_from_state()
        for document in batch
        if isinstance(document, Document)
    ]

    assert len(documents) == 1
    document = documents[0]
    assert document.source == DocumentSource.S3_COMPATIBLE
    assert document.semantic_identifier == "invoice.txt"
    assert "Счёт № 145 на оплату" in document.get_text_content()
    assert (
        document.sections[0].link
        == f"{S3_ENDPOINT_URL}/{bucket_name}/reports/invoice.txt"
    )  # type: ignore[union-attr]
