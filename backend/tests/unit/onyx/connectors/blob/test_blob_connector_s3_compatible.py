from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import BlobType, DocumentSource
from onyx.connectors.blob.config import AddressingStyle
from onyx.connectors.blob.connector import BlobStorageConnector
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.server.security.models import SSRFProtectionLevel

_CREDENTIALS: dict[str, Any] = {
    "access_key_id": "fake-key",
    "secret_access_key": "fake-secret",
}


def _make_connector(
    endpoint_url: str | None = "https://storage.yandexcloud.net",
    region_name: str | None = "ru-central1",
    addressing_style: AddressingStyle = "auto",
) -> BlobStorageConnector:
    return BlobStorageConnector(
        bucket_type=BlobType.S3_COMPATIBLE.value,
        bucket_name="test-bucket",
        endpoint_url=endpoint_url,
        region_name=region_name,
        addressing_style=addressing_style,
    )


def _with_protection_level(level: SSRFProtectionLevel) -> Any:
    return patch(
        "onyx.connectors.blob.connector.get_security_settings",
        return_value=MagicMock(ssrf_protection_level=level),
    )


def test_document_source_matches_the_blob_type() -> None:
    # BlobStorageConnector derives the document source from `bucket_type.value`
    # (connector.py: `DocumentSource(self.bucket_type.value)`), so the two
    # enums must carry the same string.
    assert DocumentSource.S3_COMPATIBLE.value == BlobType.S3_COMPATIBLE.value


def test_client_uses_the_configured_endpoint_and_checksum_settings() -> None:
    connector = _make_connector()

    with (
        _with_protection_level(SSRFProtectionLevel.VALIDATE_ALL),
        patch("onyx.connectors.blob.connector.boto3.client") as mock_client,
    ):
        connector.load_credentials(_CREDENTIALS)

    mock_client.assert_called_once()
    args, kwargs = mock_client.call_args
    assert args == ("s3",)
    assert kwargs["endpoint_url"] == "https://storage.yandexcloud.net"
    assert kwargs["aws_access_key_id"] == "fake-key"
    assert kwargs["aws_secret_access_key"] == "fake-secret"
    assert kwargs["region_name"] == "ru-central1"
    boto_config = kwargs["config"]
    assert boto_config.s3["addressing_style"] == "auto"
    assert boto_config.request_checksum_calculation == "when_required"
    assert boto_config.response_checksum_validation == "when_required"


def test_missing_region_falls_back_to_us_east_1() -> None:
    connector = _make_connector(region_name=None)

    with (
        _with_protection_level(SSRFProtectionLevel.VALIDATE_ALL),
        patch("onyx.connectors.blob.connector.boto3.client") as mock_client,
    ):
        connector.load_credentials(_CREDENTIALS)

    assert mock_client.call_args.kwargs["region_name"] == "us-east-1"


@pytest.mark.parametrize(
    "credentials",
    [
        {},
        {"access_key_id": "only-key"},
        {"secret_access_key": "only-secret"},
    ],
)
def test_missing_credentials_raises(credentials: dict[str, Any]) -> None:
    connector = _make_connector()

    with pytest.raises(ConnectorMissingCredentialError):
        connector.load_credentials(credentials)


def test_missing_endpoint_url_raises() -> None:
    connector = _make_connector(endpoint_url=None)

    with pytest.raises(ConnectorValidationError, match="endpoint URL"):
        connector.load_credentials(_CREDENTIALS)


def test_non_https_endpoint_is_rejected() -> None:
    connector = _make_connector(endpoint_url="http://storage.yandexcloud.net")

    with _with_protection_level(SSRFProtectionLevel.VALIDATE_ALL):
        with pytest.raises(ConnectorValidationError, match="https"):
            connector.load_credentials(_CREDENTIALS)


def test_cloud_metadata_endpoint_is_always_rejected() -> None:
    # 169.254.169.254 stays blocked at every protection level (the floor).
    connector = _make_connector(endpoint_url="https://169.254.169.254")

    for level in SSRFProtectionLevel:
        with _with_protection_level(level):
            with pytest.raises(ConnectorValidationError):
                connector.load_credentials(_CREDENTIALS)


def test_private_network_endpoint_follows_the_global_ssrf_setting() -> None:
    # A literal IP skips DNS resolution, keeping this test network-free.
    connector = _make_connector(endpoint_url="https://192.168.1.10")

    with (
        _with_protection_level(SSRFProtectionLevel.VALIDATE_ALL),
        pytest.raises(ConnectorValidationError),
    ):
        connector.load_credentials(_CREDENTIALS)

    with (
        _with_protection_level(SSRFProtectionLevel.DISABLED),
        patch("onyx.connectors.blob.connector.boto3.client"),
    ):
        # Does not raise: the admin opted into reaching the LAN (self-hosted
        # MinIO), same mechanism MCP servers already use.
        connector.load_credentials(_CREDENTIALS)


def test_loopback_needs_ssrf_protection_disabled() -> None:
    # Seen on the stand 2026-10-11: ALLOW_PRIVATE_NETWORK reaches LAN hosts but
    # keeps loopback blocked, so a server on the app host itself needs DISABLED.
    # https, so the scheme check does not hide the loopback check.
    connector = _make_connector(endpoint_url="https://127.0.0.1:9004")

    for level in (
        SSRFProtectionLevel.VALIDATE_ALL,
        SSRFProtectionLevel.VALIDATE_LLM,
        SSRFProtectionLevel.ALLOW_PRIVATE_NETWORK,
    ):
        with _with_protection_level(level):
            with pytest.raises(ConnectorValidationError, match="loopback|private"):
                connector.load_credentials(_CREDENTIALS)

    with (
        _with_protection_level(SSRFProtectionLevel.DISABLED),
        patch("onyx.connectors.blob.connector.boto3.client"),
    ):
        connector.load_credentials(_CREDENTIALS)


def test_plain_http_is_allowed_once_the_private_network_is_allowed() -> None:
    # A self-hosted server on the client's own network (SeaweedFS, MinIO) is
    # commonly plain http; requiring https in addition to an explicit opt-in
    # to the private network would just break that setup for no extra safety.
    connector = _make_connector(endpoint_url="http://192.168.1.10:8333")

    with (
        _with_protection_level(SSRFProtectionLevel.VALIDATE_ALL),
        pytest.raises(ConnectorValidationError),
    ):
        connector.load_credentials(_CREDENTIALS)

    with (
        _with_protection_level(SSRFProtectionLevel.ALLOW_PRIVATE_NETWORK),
        patch("onyx.connectors.blob.connector.boto3.client"),
    ):
        connector.load_credentials(_CREDENTIALS)


def test_blob_link_is_the_object_path_under_the_configured_endpoint() -> None:
    connector = _make_connector(endpoint_url="https://storage.yandexcloud.net")

    with (
        _with_protection_level(SSRFProtectionLevel.VALIDATE_ALL),
        patch("onyx.connectors.blob.connector.boto3.client") as mock_client,
    ):
        mock_client.return_value.meta.endpoint_url = "https://storage.yandexcloud.net"
        connector.load_credentials(_CREDENTIALS)

    link = connector._get_blob_link("reports/счёт.pdf")

    assert (
        link
        == "https://storage.yandexcloud.net/test-bucket/reports/%D1%81%D1%87%D1%91%D1%82.pdf"
    )
