import re
from typing import Annotated
from urllib.parse import unquote, urlsplit

from pydantic import Field

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeOpaque,
    ScopeOrdered,
)
from onyx.connectors.planning_rule import ConnectorChangeOverride

_ROOT_PATH = "root_path"
_API_PATH_PREFIX = "disk:"
# The web Disk: https://disk.yandex.ru/client/disk/<folder path>
_WEB_HOST = re.compile(r"disk\.(360\.)?yandex\.[a-z]+")
_WEB_PATH_PREFIX = "/client/disk"
DEFAULT_MAX_FILE_SIZE_MB = 20
# A file is read into memory whole, so the limit stays modest.
MAX_FILE_SIZE_MB_LIMIT = 100


class YandexDiskConnectorConfig(ConnectorConfig):
    # One folder of the Disk, e.g. "Documents/Contracts". Empty indexes the
    # whole Disk. A deeper folder narrows, a shallower one widens
    # (`yandex_disk_planning_rule`).
    root_path: Annotated[str, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())] = ""
    # Files larger than this are skipped by their listed size, before download.
    max_file_size_mb: Annotated[
        int,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeOrdered(widens_when_larger=True)),
        Field(ge=1, le=MAX_FILE_SIZE_MB_LIMIT),
    ] = DEFAULT_MAX_FILE_SIZE_MB
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE


def normalize_root_path(root_path: str) -> str:
    """The folder relative to the Disk root, without surrounding or doubled
    slashes and without the API's "disk:" prefix. A folder address from the
    browser gives its path. Empty is the whole Disk."""
    path: str = root_path.strip()
    web_url = urlsplit(path)
    if web_url.scheme in ("http", "https") and _WEB_HOST.fullmatch(
        web_url.hostname or ""
    ):
        path = unquote(web_url.path).removeprefix(_WEB_PATH_PREFIX)
    path = path.removeprefix(_API_PATH_PREFIX)
    return "/".join(part for part in path.split("/") if part.strip())


def root_api_path(root_path: str) -> str:
    """The API path of the root folder, e.g. "disk:/Documents"."""
    return f"{_API_PATH_PREFIX}/{normalize_root_path(root_path)}"


def yandex_disk_planning_rule(
    old: YandexDiskConnectorConfig, new: YandexDiskConnectorConfig
) -> ConnectorChangeOverride:
    old_root, new_root = (
        normalize_root_path(old.root_path),
        normalize_root_path(new.root_path),
    )
    if new_root == old_root:
        direction = ScopeDirection.NONE
    elif not old_root or new_root.startswith(f"{old_root}/"):
        direction = ScopeDirection.NARROW
    elif not new_root or old_root.startswith(f"{new_root}/"):
        direction = ScopeDirection.WIDEN
    else:
        # Neither folder holds the other: the change adds and removes files.
        direction = ScopeDirection.BOTH
    return ConnectorChangeOverride(scope_directions={_ROOT_PATH: direction})
