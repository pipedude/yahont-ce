from typing import Literal

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import BlobType
from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding

# S3_COMPATIBLE only; matches botocore's own `Config(s3={"addressing_style": ...})`.
AddressingStyle = Literal["auto", "path", "virtual"]


class BlobStorageCredentialBinding(CredentialBinding):
    # The connector annotates this as str and converts it with BlobType(...).
    bucket_type: BlobType
    european_residency: bool = False
    region_name: str | None = None
    # S3_COMPATIBLE only: the provider's S3 API endpoint (e.g.
    # https://storage.yandexcloud.net) and bucket addressing style.
    endpoint_url: str | None = None
    addressing_style: AddressingStyle = "auto"


class BlobStorageConnectorConfig(BlobStorageCredentialBinding, ConnectorConfig):
    bucket_name: str
    prefix: str = ""
    batch_size: int = INDEX_BATCH_SIZE
