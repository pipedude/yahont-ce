"""Yandex Disk connector: the files of one folder of the Disk, or of the whole
Disk.

Indexing and pruning walk the folder tree through the gateway. The API's flat
file listing is not used: it leaves out the files of folders that other
accounts share with this one.
"""

import mimetypes
from collections import deque
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from urllib.parse import quote, urlencode

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    SKIP_SPREADSHEET_CONTENT,
    YANDEX_DISK_CLIENT_ID,
    YANDEX_DISK_CLIENT_SECRET,
)
from onyx.configs.constants import DocumentSource, FileOrigin
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_oauth_callback_uri,
)
from onyx.connectors.cross_connector_utils.tabular_section_utils import (
    extract_and_stage_tabular_file,
    is_tabular_file,
)
from onyx.connectors.interfaces import (
    CredentialsConnector,
    CredentialsProviderInterface,
    GenerateDocumentsOutput,
    GenerateSlimDocumentOutput,
    LoadConnector,
    OAuthConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    ImageSection,
    SlimDocument,
    TabularSection,
    TextSection,
)
from onyx.connectors.yandex_disk.capability_checks import (
    check_root_folder,
    check_token,
    file_root_error,
    is_oauth_credential,
    missing_folder_error,
)
from onyx.connectors.yandex_disk.config import (
    DEFAULT_MAX_FILE_SIZE_MB,
    normalize_root_path,
    root_api_path,
)
from onyx.connectors.yandex_disk.models import (
    DIR_TYPE,
    FILE_TYPE,
    YandexDiskResource,
)
from onyx.connectors.yandex_disk.source_operations import (
    OAUTH_AUTHORIZE_URL,
    YandexDiskDownloadError,
    YandexDiskNotFoundError,
    YandexDiskSourceOperations,
    exchange_code_for_token,
)
from onyx.file_processing.extract_file_text import extract_text_and_images, get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

_FOLDER_PAGE_SIZE = 1000
# Ids per batch of the slim (pruning) listing.
_SLIM_BATCH_SIZE = 1000
_BYTES_PER_MB = 1024 * 1024
_API_PATH_PREFIX = "disk:/"
_WEB_URL = "https://disk.yandex.ru/client/disk"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
# The only rights the sign-in asks for, whatever the app is allowed to ask.
_OAUTH_SCOPE = "cloud_api:disk.read cloud_api:disk.info"


def _relative_path(api_path: str) -> str:
    """The path below the Disk root: "disk:/A/b.pdf" is "A/b.pdf"."""
    if api_path.startswith(_API_PATH_PREFIX):
        return api_path[len(_API_PATH_PREFIX) :]
    return api_path.lstrip("/")


def _parent_folder(api_path: str) -> str:
    return _relative_path(api_path).rpartition("/")[0]


def _file_link(api_path: str) -> str:
    """The web Disk folder of the file, with the file open in its viewer."""
    parent: str = _parent_folder(api_path)
    folder_url: str = f"{_WEB_URL}/{quote(parent)}" if parent else _WEB_URL
    viewer_path: str = quote(f"/disk/{_relative_path(api_path)}", safe="")
    return f"{folder_url}?idApp=client&dialog=slider&idDialog={viewer_path}"


def _document_id(item: YandexDiskResource) -> str:
    # The resource id survives a rename or a move, so the document stays one.
    return f"yandex_disk:{item.resource_id or item.path}"


def _image_file_id(item: YandexDiskResource) -> str:
    key: str = item.resource_id or item.path
    return f"yandex_disk_{key.replace(':', '_').replace('/', '_')}"


class YandexDiskConnector(
    LoadConnector, PollConnector, SlimConnector, OAuthConnector, CredentialsConnector
):
    # Every listed file carries its modification date, so a prune can list
    # only the files from the indexing start, as indexing does.
    slim_listing_honors_indexing_start = True
    # An admin of a self-hosted server pastes a token from an app of their own;
    # the sign-in button is Yahont's cloud app.
    supports_manual_credentials = True

    def __init__(
        self,
        root_path: str = "",
        max_file_size_mb: int = DEFAULT_MAX_FILE_SIZE_MB,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.root_path: str = normalize_root_path(root_path)
        self.max_file_size_bytes: int = max_file_size_mb * _BYTES_PER_MB
        self.batch_size: int = batch_size
        self._allow_images: bool = False
        self._ops: YandexDiskSourceOperations | None = None

    @property
    def ops(self) -> YandexDiskSourceOperations:
        if self._ops is None:
            raise ConnectorMissingCredentialError("Yandex Disk")
        return self._ops

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.set_credentials_provider(
            OnyxStaticCredentialsProvider(
                None, DocumentSource.YANDEX_DISK.value, credentials
            )
        )
        return None

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self._ops = YandexDiskSourceOperations(
            credentials_provider=credentials_provider
        )

    @classmethod
    def oauth_enabled(cls) -> bool:
        return bool(YANDEX_DISK_CLIENT_ID and YANDEX_DISK_CLIENT_SECRET)

    @classmethod
    def oauth_id(cls) -> DocumentSource:
        return DocumentSource.YANDEX_DISK

    @classmethod
    def oauth_authorization_url(
        cls,
        base_domain: str,
        state: str,
        additional_kwargs: dict[str, str],  # noqa: ARG003
        code_challenge: str | None = None,  # noqa: ARG003
    ) -> str:
        if not YANDEX_DISK_CLIENT_ID:
            raise ValueError("YANDEX_DISK_CLIENT_ID environment variable must be set")
        query: str = urlencode(
            {
                "response_type": "code",
                "client_id": YANDEX_DISK_CLIENT_ID,
                "redirect_uri": get_oauth_callback_uri(
                    base_domain, DocumentSource.YANDEX_DISK.value
                ),
                "scope": _OAUTH_SCOPE,
                "state": state,
                # Shows the consent screen, so the admin picks the account.
                "force_confirm": "yes",
            }
        )
        return f"{OAUTH_AUTHORIZE_URL}?{query}"

    @classmethod
    def oauth_code_to_token(
        cls,
        base_domain: str,  # noqa: ARG003
        code: str,
        additional_kwargs: dict[str, str],  # noqa: ARG003
        code_verifier: str | None = None,  # noqa: ARG003
    ) -> dict[str, Any]:
        return exchange_code_for_token(code)

    def set_allow_images(self, value: bool) -> None:
        self._allow_images = value

    def validate_connector_settings(self) -> None:
        """The checks' helpers: a token the API accepts, a root folder that
        exists and is a folder."""
        oauth: bool = is_oauth_credential(
            self.ops.credentials_provider.get_credentials()
        )
        check_token(self.ops, oauth)
        check_root_folder(self.ops, self.root_path, oauth)

    def _file_pages(self) -> Iterator[list[YandexDiskResource]]:
        """The files of each folder page, breadth first from the root folder.
        A file or folder listed twice comes once. A subfolder deleted during
        the walk is skipped; any other failure stops the walk, so a prune never
        reads a partial listing as deletions."""
        root: str = root_api_path(self.root_path)
        folders: deque[str] = deque([root])
        seen: set[str] = set()
        while folders:
            path: str = folders.popleft()
            offset: int = 0
            while True:
                try:
                    page = self.ops.list_folder(
                        path=path, offset=offset, limit=_FOLDER_PAGE_SIZE
                    )
                except YandexDiskNotFoundError as e:
                    if path == root:
                        raise missing_folder_error(self.root_path) from e
                    logger.warning("Folder %s disappeared during the walk.", path)
                    break
                if page.type != DIR_TYPE:
                    if path == root:
                        raise file_root_error(self.root_path)
                    break
                files: list[YandexDiskResource] = []
                for item in page.items:
                    key: str = item.resource_id or item.path
                    if key in seen:
                        continue
                    seen.add(key)
                    if item.type == DIR_TYPE:
                        folders.append(item.path)
                    elif item.type == FILE_TYPE:
                        files.append(item)
                yield files
                offset += len(page.items)
                if not page.items or (page.total is not None and offset >= page.total):
                    break

    def _listed_as_document(self, item: YandexDiskResource) -> bool:
        """The skips that need no download: a file over the size limit, an
        extension no extractor reads, an image while images are off."""
        if item.size is not None and item.size > self.max_file_size_bytes:
            return False
        extension: str = get_file_ext(item.name)
        if extension not in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS:
            return False
        if extension in OnyxFileExtensions.IMAGE_EXTENSIONS:
            return self._allow_images
        return True

    def _document(
        self,
        item: YandexDiskResource,
        sections: Sequence[TextSection | ImageSection | TabularSection],
        file_id: str | None = None,
    ) -> Document:
        parent: str = _parent_folder(item.path)
        return Document(
            id=_document_id(item),
            sections=sections,
            source=DocumentSource.YANDEX_DISK,
            semantic_identifier=item.name,
            doc_updated_at=item.modified,
            doc_created_at=item.created,
            metadata={"folder": f"/{parent}"},
            file_id=file_id,
        )

    def _to_document(self, item: YandexDiskResource) -> Document | None:
        """The file as a document, or None when it is skipped: deleted before
        its download, refused by the download server after the retries, over
        the size limit, or unreadable. A skipped file comes back when it
        changes or on a full re-index. Any other API error stops the run, so
        the next run retries the file."""
        link: str = _file_link(item.path)
        is_image: bool = get_file_ext(item.name) in OnyxFileExtensions.IMAGE_EXTENSIONS
        raw_file_callback = self.raw_file_callback
        is_tabular: bool = not is_image and is_tabular_file(item.name)
        if is_tabular and raw_file_callback is None:
            logger.warning(
                "Skipping tabular file %s because raw_file_callback is not set",
                item.path,
            )
            return None
        try:
            content: bytes | None = self.ops.download_file(
                path=item.path, max_size_bytes=self.max_file_size_bytes
            )
        except YandexDiskNotFoundError:
            logger.info("%s was deleted before its download.", item.path)
            return None
        except YandexDiskDownloadError as e:
            logger.warning("Skipping %s: %s", item.path, e)
            return None
        if content is None:
            return None
        try:
            if is_image:
                section, _ = store_image_and_create_section(
                    image_data=content,
                    file_id=_image_file_id(item),
                    display_name=item.name,
                    link=link,
                    media_type=item.mime_type or "application/octet-stream",
                    file_origin=FileOrigin.CONNECTOR,
                )
                return self._document(item, [section])
            if is_tabular and raw_file_callback is not None:
                content_type, _ = mimetypes.guess_type(item.name)
                result = extract_and_stage_tabular_file(
                    file=BytesIO(content),
                    file_name=item.name,
                    content_type=content_type or "application/octet-stream",
                    raw_file_callback=raw_file_callback,
                    link=link,
                    skip_content=SKIP_SPREADSHEET_CONTENT,
                )
                if not result.sections:
                    logger.warning("No content extracted from %s", item.path)
                    return None
                return self._document(
                    item, result.sections, file_id=result.staged_file_id
                )
            extraction = extract_text_and_images(BytesIO(content), file_name=item.name)
            return self._document(
                item, [TextSection(link=link, text=extraction.text_content.strip())]
            )
        except Exception:
            logger.exception("Error processing Yandex Disk file %s", item.path)
            return None

    def _documents(self, start: datetime, end: datetime) -> GenerateDocumentsOutput:
        batch: list[Document | HierarchyNode] = []
        for files in self._file_pages():
            for item in files:
                if not self._listed_as_document(item):
                    continue
                if item.modified is not None and not start <= item.modified <= end:
                    continue
                document: Document | None = self._to_document(item)
                if document is None:
                    continue
                batch.append(document)
                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []
        if batch:
            yield batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._documents(_EPOCH, datetime.now(timezone.utc))

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        return self._documents(
            datetime.fromtimestamp(start, tz=timezone.utc),
            datetime.fromtimestamp(end, tz=timezone.utc),
        )

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """The ids a full run yields, from the listing alone, so pruning
        downloads nothing. A file that a full run skips after its download (a
        read or parse error) stays listed: one failed read must not prune its
        document."""
        floor: datetime | None = (
            datetime.fromtimestamp(start, tz=timezone.utc)
            if start is not None
            else None
        )
        batch: list[SlimDocument | HierarchyNode] = []
        for files in self._file_pages():
            if callback:
                if callback.should_stop():
                    raise RuntimeError(
                        "Yandex Disk slim retrieval: stop signal detected"
                    )
                callback.progress("yandex_disk_slim_retrieval", 1)
            for item in files:
                if not self._listed_as_document(item):
                    continue
                if (
                    floor is not None
                    and item.modified is not None
                    and item.modified < floor
                ):
                    continue
                batch.append(SlimDocument(id=_document_id(item)))
                if len(batch) >= _SLIM_BATCH_SIZE:
                    yield batch
                    batch = []
        if batch:
            yield batch
