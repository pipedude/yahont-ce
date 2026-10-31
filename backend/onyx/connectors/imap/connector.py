import base64
import copy
import email
import hashlib
import imaplib
import os
import re
import ssl
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import getaddresses
from enum import Enum
from typing import Any, NamedTuple, cast

import bs4
from pydantic import BaseModel

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    RateLimitedValidationError,
    UnexpectedValidationError,
    UnreachableValidationError,
)
from onyx.connectors.imap.config import DEFAULT_IMAP_PORT_NUMBER
from onyx.connectors.imap.models import EmailHeaders
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    CredentialsConnector,
    CredentialsProviderInterface,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    ConnectorFailure,
    Document,
    DocumentFailure,
    SlimDocument,
    TextSection,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()


_IMAP_OKAY_STATUS = "OK"
_PAGE_SIZE = 100
# Message-ID headers fetched per FETCH command by the slim (pruning) pass.
_SLIM_BATCH_SIZE = 500
_UNSELECTABLE_ATTRIBUTES = {"\\noselect", "\\nonexistent"}
# In order of preference.
_BODY_CONTENT_TYPES = ("text/plain", "text/html")
# Mail.ru flags its spam folder `\Spam`; RFC 6154 names it `\Junk`.
_JUNK_AND_TRASH_ATTRIBUTES = {"\\junk", "\\spam", "\\trash"}
_USERNAME_KEY = "imap_username"
_PASSWORD_KEY = "imap_password"
# RFC 5530 response codes of a LOGIN refusal that a later try can clear. Any
# other refusal is a rejected account.
_TEMPORARY_LOGIN_REFUSALS: dict[str, type[UnexpectedValidationError]] = {
    "UNAVAILABLE": UnreachableValidationError,
    "INUSE": RateLimitedValidationError,
    "LIMIT": RateLimitedValidationError,
    "SERVERBUG": UnexpectedValidationError,
}


class LoginRefusedError(imaplib.IMAP4.error):
    """The server answered LOGIN with NO or BAD. The message is the server's text."""


class CurrentMailbox(BaseModel):
    mailbox: str
    todo_email_ids: list[str]


# An email has a list of mailboxes.
# Each mailbox has a list of email-ids inside of it.
#
# Usage:
# To use this checkpointer, first fetch all the mailboxes.
# Then, pop a mailbox and fetch all of its email-ids.
# Then, pop each email-id and fetch its content (and parse it, etc..).
# When you have popped all email-ids for this mailbox, pop the next mailbox and repeat the above process until you're done.
#
# For initial checkpointing, set both fields to `None`.
class ImapCheckpoint(ConnectorCheckpoint):
    todo_mailboxes: list[str] | None = None
    current_mailbox: CurrentMailbox | None = None


class LoginState(str, Enum):
    LoggedIn = "logged_in"
    LoggedOut = "logged_out"


class ImapConnector(
    CredentialsConnector,
    CheckpointedConnectorWithPermSync[ImapCheckpoint],
    SlimConnector,
):
    # Provider presets override these (`onyx.connectors.ru_mail`).
    _source: DocumentSource = DocumentSource.IMAP
    _skip_junk_and_trash: bool = False

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_IMAP_PORT_NUMBER,
        mailboxes: list[str] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._mailboxes = mailboxes
        self._credentials: dict[str, Any] | None = None

    @property
    def credentials(self) -> dict[str, Any]:
        if not self._credentials:
            raise RuntimeError(
                "Credentials have not been initialized; call `set_credentials_provider` first"
            )
        return self._credentials

    def _get_mail_client(self) -> imaplib.IMAP4_SSL:
        """
        Returns a new `imaplib.IMAP4_SSL` instance.

        The `imaplib.IMAP4_SSL` object is supposed to be an "ephemeral" object; it's not something that you can login,
        logout, then log back into again. I.e., the following will fail:

        ```py
        mail_client.login(..)
        mail_client.logout();
        mail_client.login(..)
        ```

        Therefore, you need a fresh, new instance in order to operate with IMAP. This function gives one to you.

        # Notes
        This function will throw an error if the credentials have not yet been set.
        """

        def get_or_raise(name: str) -> str:
            value = self.credentials.get(name)
            if not value:
                raise RuntimeError(f"Credential item {name=} was not found")
            if not isinstance(value, str):
                raise RuntimeError(
                    f"Credential item {name=} must be of type str, instead received {type(name)=}"
                )
            return value

        return _connect_and_login(
            host=self._host,
            port=self._port,
            username=get_or_raise(_USERNAME_KEY),
            password=get_or_raise(_PASSWORD_KEY),
        )

    def _mailboxes_to_index(self, mail_client: imaplib.IMAP4_SSL) -> list[str]:
        """The quoted, encoded mailbox names one run reads: the configured
        ones, or every selectable mailbox (presets skip Spam and Trash)."""
        if self._mailboxes:
            return _sanitize_mailbox_names(self._mailboxes)

        fetched_mailboxes = _fetch_all_mailboxes_for_email_account(
            mail_client=mail_client,
            skip_junk_and_trash=self._skip_junk_and_trash,
        )
        if not fetched_mailboxes:
            raise RuntimeError("Failed to find any mailboxes for this email account")
        return _sanitize_mailbox_names(fetched_mailboxes)

    def _load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ImapCheckpoint,
        include_perm_sync: bool,
    ) -> CheckpointOutput[ImapCheckpoint]:
        # Each checkpoint step is one IMAP session: log it out even when the
        # step fails, or the provider's per-account session limit fills up.
        mail_client = self._get_mail_client()
        try:
            return (
                yield from self._load_with_client(
                    mail_client, start, end, checkpoint, include_perm_sync
                )
            )
        finally:
            _logout(mail_client)

    def _load_with_client(
        self,
        mail_client: imaplib.IMAP4_SSL,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ImapCheckpoint,
        include_perm_sync: bool,
    ) -> CheckpointOutput[ImapCheckpoint]:
        checkpoint = copy.deepcopy(checkpoint)
        checkpoint.has_more = True

        if checkpoint.todo_mailboxes is None:
            # This is the dummy checkpoint.
            # Fill it with mailboxes first.
            checkpoint.todo_mailboxes = self._mailboxes_to_index(mail_client)
            return checkpoint

        if (
            not checkpoint.current_mailbox
            or not checkpoint.current_mailbox.todo_email_ids
        ):
            if not checkpoint.todo_mailboxes:
                checkpoint.has_more = False
                return checkpoint

            mailbox = checkpoint.todo_mailboxes.pop()
            email_ids = _fetch_email_ids_in_mailbox(
                mail_client=mail_client,
                mailbox=mailbox,
                start=start,
                end=end,
            )
            checkpoint.current_mailbox = CurrentMailbox(
                mailbox=mailbox,
                todo_email_ids=email_ids,
            )

        _select_mailbox(
            mail_client=mail_client, mailbox=checkpoint.current_mailbox.mailbox
        )
        folder = _decode_mailbox_name(checkpoint.current_mailbox.mailbox)
        current_todos = cast(
            list, copy.deepcopy(checkpoint.current_mailbox.todo_email_ids[:_PAGE_SIZE])
        )
        checkpoint.current_mailbox.todo_email_ids = (
            checkpoint.current_mailbox.todo_email_ids[_PAGE_SIZE:]
        )

        for email_id in current_todos:
            fetched_email = _fetch_email(mail_client=mail_client, email_id=email_id)
            if not fetched_email:
                logger.warning(
                    "Failed to fetch message email_id=%r; skipping", email_id
                )
                continue

            yield _email_to_document(
                fetched_email,
                include_perm_sync=include_perm_sync,
                source=self._source,
                folder=folder,
            )

        return checkpoint

    # impls for BaseConnector

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError("Use `set_credentials_provider` instead")

    def validate_connector_settings(self) -> None:
        # Every index attempt runs this, and an error that is not an
        # `UnexpectedValidationError` pauses the pair (`run_docfetching.py`),
        # so only a rejected account or a missing mailbox stops indexing.
        server = f"{self._host}:{self._port}"
        try:
            mail_client = self._get_mail_client()
            try:
                self._check_configured_mailboxes(mail_client)
            finally:
                _logout(mail_client)
        except LoginRefusedError as e:
            code = re.match(r"\[([A-Za-z]+)", str(e))
            temporary = (
                _TEMPORARY_LOGIN_REFUSALS.get(code.group(1).upper()) if code else None
            )
            if temporary:
                raise temporary(
                    f"The IMAP server {server} refused the login for now: {e}"
                ) from e
            raise CredentialInvalidError(
                f"The IMAP server {server} rejected the login: {e}"
            ) from e
        except imaplib.IMAP4.error as e:
            # Includes `IMAP4.abort` after every retry.
            raise UnreachableValidationError(
                f"The server {server} did not answer as an IMAP server: {e}"
            ) from e
        except OSError as e:
            raise UnreachableValidationError(
                f"Cannot connect to the IMAP server {server}: {e}"
            ) from e

    def _check_configured_mailboxes(self, mail_client: imaplib.IMAP4_SSL) -> None:
        """A typed mailbox the server does not have fails here, when the
        connector is created, instead of failing every index run."""
        names = [name for name in self._mailboxes or [] if name]
        for name, quoted in zip(names, _sanitize_mailbox_names(names), strict=True):
            status, _data = mail_client.select(mailbox=quoted, readonly=True)
            if status != _IMAP_OKAY_STATUS:
                raise ConnectorValidationError(
                    f"The mail account has no mailbox named {name!r}"
                )

    # impls for SlimConnector

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Every message id, for pruning. Reads only the Message-ID header of
        each message, not the message itself (the full run downloads every
        body). The id set matches the full run: same mailboxes, and a message
        without a Message-ID is fetched whole and hashed the same way."""
        mail_client = self._get_mail_client()
        try:
            for mailbox in self._mailboxes_to_index(mail_client):
                _select_mailbox(mail_client=mail_client, mailbox=mailbox)
                status, data = mail_client.search(None, "ALL")
                if status != _IMAP_OKAY_STATUS or not data:
                    raise RuntimeError(f"Failed to list {mailbox=}; {status=}")
                email_ids = [email_id.decode() for email_id in data[0].split()]

                for batch_start in range(0, len(email_ids), _SLIM_BATCH_SIZE):
                    if callback and callback.should_stop():
                        raise RuntimeError("IMAP slim retrieval stopped by callback")
                    message_ids = _fetch_message_ids(
                        mail_client=mail_client,
                        email_ids=email_ids[
                            batch_start : batch_start + _SLIM_BATCH_SIZE
                        ],
                    )
                    if callback:
                        callback.progress("imap_slim_docs", len(message_ids))
                    yield [SlimDocument(id=message_id) for message_id in message_ids]
        finally:
            _logout(mail_client)

    # impls for CredentialsConnector

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self._credentials = credentials_provider.get_credentials()

    # impls for CheckpointedConnector

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ImapCheckpoint,
    ) -> CheckpointOutput[ImapCheckpoint]:
        return self._load_from_checkpoint(
            start=start, end=end, checkpoint=checkpoint, include_perm_sync=False
        )

    def build_dummy_checkpoint(self) -> ImapCheckpoint:
        return ImapCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> ImapCheckpoint:
        return ImapCheckpoint.model_validate_json(json_data=checkpoint_json)

    # impls for CheckpointedConnectorWithPermSync

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ImapCheckpoint,
    ) -> CheckpointOutput[ImapCheckpoint]:
        return self._load_from_checkpoint(
            start=start, end=end, checkpoint=checkpoint, include_perm_sync=True
        )


def _fetch_all_mailboxes_for_email_account(
    mail_client: imaplib.IMAP4_SSL, skip_junk_and_trash: bool
) -> list[str]:
    status, mailboxes_data = mail_client.list(directory="*", pattern="*")
    if status != _IMAP_OKAY_STATUS:
        raise RuntimeError(f"Failed to fetch mailboxes; {status=}")

    mailboxes = []

    for mailboxes_raw in mailboxes_data:
        if isinstance(mailboxes_raw, bytes):
            mailboxes_str = mailboxes_raw.decode()
        elif isinstance(mailboxes_raw, str):
            mailboxes_str = mailboxes_raw
        else:
            logger.warning(
                "Expected the mailbox data to be of type str, instead got type(mailboxes_raw)=%r %s; skipping",
                type(mailboxes_raw),
                mailboxes_raw,
            )
            continue

        # The mailbox LIST response output can be found here:
        # https://www.rfc-editor.org/rfc/rfc3501.html#section-7.2.2
        #
        # The general format is:
        # `(<name-attributes>) <hierarchy-delimiter> <mailbox-name>`
        #
        # The below regex matches on that pattern: the name attributes, the delimiter, and the mailbox-name.
        match = re.match(r'\(([^)]*)\)\s+"([^"]+)"\s+"?(.+?)"?$', mailboxes_str)
        if not match:
            logger.warning(
                "Invalid mailbox-data formatting structure: mailboxes_str=%r; skipping",
                mailboxes_str,
            )
            continue

        # Attributes are case-insensitive (RFC 3501, RFC 6154 for \Junk and \Trash).
        attributes = {attribute.lower() for attribute in match.group(1).split()}
        skipped = _UNSELECTABLE_ATTRIBUTES | (
            _JUNK_AND_TRASH_ATTRIBUTES if skip_junk_and_trash else set()
        )
        if attributes & skipped:
            continue

        mailbox = match.group(3)
        mailboxes.append(mailbox)

    return mailboxes


def _select_mailbox(mail_client: imaplib.IMAP4_SSL, mailbox: str) -> None:
    status, _ids = mail_client.select(mailbox=mailbox, readonly=True)
    if status != _IMAP_OKAY_STATUS:
        raise RuntimeError(f"Failed to select {mailbox=}")


def _fetch_email_ids_in_mailbox(
    mail_client: imaplib.IMAP4_SSL,
    mailbox: str,
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
) -> list[str]:
    _select_mailbox(mail_client=mail_client, mailbox=mailbox)

    # SEARCH compares dates only and BEFORE is exclusive (RFC 3501 section 6.4.4),
    # so search up to the day after `end`; otherwise a poll window inside one day
    # finds nothing and today's mail waits for the next day. Re-fetched messages
    # keep their Message-ID, so the overlap does not duplicate documents.
    end_str = (
        datetime.fromtimestamp(end, tz=timezone.utc) + timedelta(days=1)
    ).strftime("%d-%b-%Y")
    # No start means "all mail": send no SINCE. Mail.ru answers
    # `SINCE "01-Jan-1970"` with an empty result, so a first run found nothing.
    if start > 0:
        start_str = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%d-%b-%Y")
        search_criteria = f'(SINCE "{start_str}" BEFORE "{end_str}")'
    else:
        search_criteria = f'BEFORE "{end_str}"'

    status, email_ids_byte_array = mail_client.search(None, search_criteria)

    if status != _IMAP_OKAY_STATUS or not email_ids_byte_array:
        raise RuntimeError(f"Failed to fetch email ids; {status=}")

    email_ids: bytes = email_ids_byte_array[0]

    return [email_id.decode() for email_id in email_ids.split()]


class _FetchedEmail(NamedTuple):
    message: Message
    raw: bytes
    # When the server received the message (INTERNALDATE); the fallback for a
    # missing or unparseable Date header.
    internal_date: datetime | None


@retry_builder(
    tries=4,
    delay=2,
    max_delay=10,
    # A server that drops the session (seen: Yandex answering CAPABILITY with
    # "problems with connection") or a network blip. A refused login is
    # `LoginRefusedError`, not `IMAP4.abort`, and is not retried.
    exceptions=(imaplib.IMAP4.abort, ConnectionError, TimeoutError),
)
def _connect_and_login(
    host: str, port: int, username: str, password: str
) -> imaplib.IMAP4_SSL:
    # imaplib defaults to an unverified context; pass an explicit one so the
    # certificate and hostname are checked before credentials are sent.
    mail_client = imaplib.IMAP4_SSL(
        host=host,
        port=port,
        ssl_context=ssl.create_default_context(),
    )
    try:
        status, _data = mail_client.login(user=username, password=password)
        if status != _IMAP_OKAY_STATUS:
            raise RuntimeError(f"Failed to log into imap server; {status=}")
    except Exception as e:
        _logout(mail_client)
        if isinstance(e, imaplib.IMAP4.error) and not isinstance(
            e, imaplib.IMAP4.abort
        ):
            raise LoginRefusedError(str(e)) from e
        raise
    return mail_client


def _logout(mail_client: imaplib.IMAP4_SSL) -> None:
    """End the IMAP session. A connection that already dropped has nothing
    left to close, so its error is not raised."""
    try:
        mail_client.logout()
    except (imaplib.IMAP4.error, OSError) as e:
        logger.debug("IMAP logout failed: %s", e)


def _content_hash_id(raw_email: bytes) -> str:
    """The id of a message without a Message-ID; stable across runs."""
    return "imap-sha256:" + hashlib.sha256(raw_email).hexdigest()


def _fetch_message_ids(
    mail_client: imaplib.IMAP4_SSL, email_ids: list[str]
) -> list[str]:
    """The document ids of the given messages, read from the Message-ID header
    only. A message without one is fetched whole for its content hash. Raises
    rather than skipping: a missing id would make pruning delete the message."""
    status, msg_data = mail_client.fetch(
        message_set=",".join(email_ids),
        message_parts="(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])",
    )
    if status != _IMAP_OKAY_STATUS or not msg_data:
        raise RuntimeError(f"Failed to fetch Message-ID headers; {status=}")

    message_ids: list[str] = []
    for item in msg_data:
        # The response interleaves (metadata, header) tuples with b")".
        if not isinstance(item, tuple):
            continue
        metadata, header = item
        message_id = EmailHeaders.from_email_msg(
            email_msg=email.message_from_bytes(header)
        ).id
        if not message_id:
            email_id = metadata.split(b" ", 1)[0].decode()
            fetched_email = _fetch_email(mail_client=mail_client, email_id=email_id)
            if fetched_email is None:
                raise RuntimeError(f"Failed to fetch message {email_id=}")
            message_id = _content_hash_id(fetched_email.raw)
        message_ids.append(message_id)

    if len(message_ids) != len(email_ids):
        raise RuntimeError(
            f"Expected {len(email_ids)} Message-ID headers, got {len(message_ids)}"
        )
    return message_ids


def _fetch_email(mail_client: imaplib.IMAP4_SSL, email_id: str) -> _FetchedEmail | None:
    status, msg_data = mail_client.fetch(
        message_set=email_id, message_parts="(INTERNALDATE RFC822)"
    )
    if status != _IMAP_OKAY_STATUS or not msg_data:
        return None

    data = msg_data[0]
    if not isinstance(data, tuple):
        raise RuntimeError(
            f"Message data should be a tuple; instead got a {type(data)=} {data=}"
        )

    metadata, raw_email = data
    return _FetchedEmail(
        message=email.message_from_bytes(raw_email),
        raw=raw_email,
        internal_date=_parse_internal_date(metadata),
    )


def _parse_internal_date(fetch_metadata: bytes) -> datetime | None:
    # e.g. `7 (INTERNALDATE " 1-Oct-2026 10:00:00 +0300" RFC822 {123}`
    match = re.search(rb'INTERNALDATE "([^"]+)"', fetch_metadata)
    if not match:
        return None
    try:
        return datetime.strptime(
            match.group(1).decode().strip(), "%d-%b-%Y %H:%M:%S %z"
        ).astimezone(timezone.utc)
    except ValueError:
        return None


def _email_to_document(
    fetched_email: _FetchedEmail,
    include_perm_sync: bool,
    source: DocumentSource,
    folder: str | None = None,
) -> Document | ConnectorFailure:
    """One message, one document. A message that cannot be converted becomes a
    `ConnectorFailure` (like a Gmail thread), so the rest of the run continues."""
    document_id = _content_hash_id(fetched_email.raw)
    try:
        email_headers = EmailHeaders.from_email_msg(email_msg=fetched_email.message)
        document_id = email_headers.id or document_id
        return _convert_email_headers_and_body_into_document(
            email_msg=fetched_email.message,
            email_headers=email_headers,
            include_perm_sync=include_perm_sync,
            source=source,
            document_id=document_id,
            internal_date=fetched_email.internal_date,
            folder=folder,
        )
    except Exception as e:
        logger.warning("Failed to convert email %s: %s", document_id, e)
        return ConnectorFailure(
            failed_document=DocumentFailure(document_id=document_id),
            failure_message=f"Failed to convert email {document_id}",
            exception=e,
        )


def _convert_email_headers_and_body_into_document(
    email_msg: Message,
    email_headers: EmailHeaders,
    include_perm_sync: bool,
    source: DocumentSource,
    document_id: str,
    internal_date: datetime | None,
    folder: str | None = None,
) -> Document:
    # Modeled on Gmail's `thread_to_document`: the sender is the primary owner,
    # recipients are secondary owners, header lines go into the text, and the
    # Date header sets doc_created_at/doc_updated_at (the date the LLM sees and
    # the field recency and time filters use).
    sender = _parse_sender(email_headers.sender)
    recipients = {
        recipient_addr: recipient_name
        for raw_header in (email_headers.recipients, email_headers.cc)
        if raw_header
        for recipient_name, recipient_addr in _parse_addrs(raw_header=raw_header)
    }

    primary_owners = (
        [BasicExpertInfo(display_name=sender[0], email=sender[1])] if sender else []
    )
    secondary_owners = [
        BasicExpertInfo(display_name=recipient_name, email=recipient_addr)
        for recipient_addr, recipient_name in recipients.items()
        if not sender or recipient_addr != sender[1]
    ]

    participant_emails = set(recipients) | ({sender[1]} if sender else set())
    external_access = (
        ExternalAccess(
            external_user_emails=participant_emails,
            external_user_group_ids=set(),
            is_public=False,
        )
        if include_perm_sync
        else None
    )

    sent_at = email_headers.date or internal_date
    if sent_at is not None:
        # A Date header without a zone is read as UTC.
        sent_at = (
            sent_at.replace(tzinfo=timezone.utc)
            if sent_at.tzinfo is None
            else sent_at.astimezone(timezone.utc)
        )

    header_lines = "".join(
        f"{name}: {value}\n"
        for name, value in (
            ("from", email_headers.sender),
            ("to", email_headers.recipients),
            ("cc", email_headers.cc),
            ("subject", email_headers.subject),
            # Gmail adds the labels; the IMAP analog is the folder.
            ("folder", folder),
        )
        if value
    )
    email_body = _parse_email_body(email_msg=email_msg, email_headers=email_headers)

    return Document(
        id=document_id,
        title=email_headers.subject,
        semantic_identifier=email_headers.subject,
        metadata={},
        source=source,
        sections=[TextSection(text=f"{email_body}\n{header_lines}")],
        primary_owners=primary_owners,
        secondary_owners=secondary_owners,
        doc_created_at=sent_at,
        doc_updated_at=sent_at,
        external_access=external_access,
    )


def _parse_sender(raw_header: str | None) -> tuple[str, str] | None:
    """The (name, address) of the sender, or None when the From header is
    missing or holds no address."""
    addrs = _parse_addrs(raw_header=raw_header) if raw_header else []
    if not addrs:
        logger.warning("Email has no parseable sender: raw_header=%r", raw_header)
        return None
    return addrs[0]


def _parse_email_body(
    email_msg: Message,
    email_headers: EmailHeaders,
) -> str:
    # Like Gmail, read the text/plain part; fall back to text/html for
    # HTML-only mail. Attachments are not the body.
    texts: dict[str, str] = {}
    for part in email_msg.walk():
        if part.is_multipart():
            # Multipart parts are *containers* for other parts, not the actual content itself.
            # Therefore, we skip until we find the individual parts instead.
            continue

        content_type = part.get_content_type()
        if (
            content_type not in _BODY_CONTENT_TYPES
            or content_type in texts
            or part.get_content_disposition() == "attachment"
        ):
            continue

        charset = part.get_content_charset() or "utf-8"

        try:
            raw_payload = part.get_payload(decode=True)
            if not isinstance(raw_payload, bytes):
                logger.warning(
                    "Payload section from email was expected to be an array of bytes, instead got type(raw_payload)=%r, raw_payload=%r",
                    type(raw_payload),
                    raw_payload,
                )
                continue
            texts[content_type] = raw_payload.decode(charset)
        except (UnicodeDecodeError, LookupError) as e:
            logger.warning("Could not decode part with charset %s: %s", charset, e)
            continue

    body = next(
        (
            texts[content_type]
            for content_type in _BODY_CONTENT_TYPES
            if texts.get(content_type)
        ),
        None,
    )
    if not body:
        logger.warning(
            "Email with email_headers.id=%r has an empty body; returning an empty string",
            email_headers.id,
        )
        return ""

    soup = bs4.BeautifulSoup(markup=body, features="html.parser")

    return " ".join(str_section for str_section in soup.stripped_strings)


def _sanitize_mailbox_names(mailboxes: list[str]) -> list[str]:
    """
    Mailboxes with special characters in them must be enclosed by double-quotes, as per the IMAP protocol.
    Just to be safe, we wrap *all* mailboxes with double-quotes.
    """
    return [f'"{_encode_mailbox_name(mailbox)}"' for mailbox in mailboxes if mailbox]


def _encode_mailbox_name(mailbox: str) -> str:
    """
    Encodes a typed-in name like `Отправленные` to IMAP modified UTF-7 (RFC 3501 section 5.1.3).
    A pure-ASCII name is returned as is: servers list names already encoded, so they must not be encoded twice.
    """
    if mailbox.isascii():
        return mailbox

    encoded: list[str] = []
    pending: list[str] = []

    def flush_pending() -> None:
        if pending:
            utf16 = "".join(pending).encode("utf-16-be")
            encoded.append(
                "&"
                + base64.b64encode(utf16).decode().rstrip("=").replace("/", ",")
                + "-"
            )
            pending.clear()

    for char in mailbox:
        if " " <= char <= "~":
            flush_pending()
            encoded.append("&-" if char == "&" else char)
        else:
            pending.append(char)
    flush_pending()
    return "".join(encoded)


def _decode_mailbox_name(mailbox: str) -> str:
    """The readable name of a quoted modified UTF-7 mailbox name, e.g.
    `"&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-"` -> `Отправленные`. A segment that is
    not valid modified UTF-7 is kept as listed."""

    def decode_segment(match: re.Match[str]) -> str:
        segment = match.group(1)
        if not segment:
            return "&"
        try:
            return base64.b64decode(
                segment.replace(",", "/") + "=" * (-len(segment) % 4), validate=True
            ).decode("utf-16-be")
        except ValueError:
            return match.group(0)

    return re.sub(r"&([^-]*)-", decode_segment, mailbox.strip('"'))


def _parse_addrs(raw_header: str) -> list[tuple[str, str]]:
    # `getaddresses` keeps a quoted name with a comma (`"Петров, Иван" <a@b>`)
    # whole; a value without `@` is a name, not an address.
    return [(name, addr) for name, addr in getaddresses([raw_header]) if "@" in addr]


if __name__ == "__main__":
    import time

    from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
    from tests.daily.connectors.utils import load_all_from_connector

    host = os.environ.get("IMAP_HOST")
    mailboxes_str = os.environ.get("IMAP_MAILBOXES")
    username = os.environ.get("IMAP_USERNAME")
    password = os.environ.get("IMAP_PASSWORD")

    mailboxes = (
        [mailbox.strip() for mailbox in mailboxes_str.split(",")]
        if mailboxes_str
        else []
    )

    if not host:
        raise RuntimeError("`IMAP_HOST` must be set")

    imap_connector = ImapConnector(
        host=host,
        mailboxes=mailboxes,
    )

    imap_connector.set_credentials_provider(
        OnyxStaticCredentialsProvider(
            tenant_id=None,
            connector_name=DocumentSource.IMAP,
            credential_json={
                _USERNAME_KEY: username,
                _PASSWORD_KEY: password,
            },
        )
    )

    for doc in load_all_from_connector(
        connector=imap_connector,
        start=0,
        end=time.time(),
    ).documents:
        print(doc)
