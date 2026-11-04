"""Plain data the Yandex Disk gateway returns."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

FILE_TYPE: str = "file"
DIR_TYPE: str = "dir"


class YandexDiskResource(BaseModel):
    """One file or folder as the Disk API lists it. ``path`` is the API path
    (``disk:/Folder/file.pdf``); ``resource_id`` stays the same when the file
    is renamed or moved."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    name: str
    path: str
    type: str
    resource_id: str | None = None
    created: datetime | None = None
    modified: datetime | None = None
    size: int | None = None
    mime_type: str | None = None


class YandexDiskFolder(BaseModel):
    """One page of a folder's contents. A file path answers with its own type
    and no items. ``total`` counts every item of the folder."""

    model_config = ConfigDict(frozen=True)

    path: str
    type: str
    items: list[YandexDiskResource]
    total: int | None = None


class YandexDiskInfo(BaseModel):
    """The account behind the token, as far as the Disk API names it."""

    model_config = ConfigDict(frozen=True)

    login: str | None = None
    display_name: str | None = None
