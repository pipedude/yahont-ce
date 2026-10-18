"""IMAP sessions are logged out, and pruning lists Message-IDs only.

The fake server below speaks just enough IMAP for the connector: LIST, SELECT,
SEARCH, FETCH of `(INTERNALDATE RFC822)` and of the Message-ID header, LOGOUT.
"""

import email
import imaplib
import re
from collections.abc import Callable, Iterator
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.imap.connector import ImapCheckpoint, ImapConnector
from onyx.connectors.models import Document, SlimDocument
from onyx.connectors.ru_mail.connector import YandexMailConnector

_OK = "OK"

# The fake's `list` method shadows the builtin inside its class body, so its
# annotations use these aliases.
_Response = tuple[str, list[bytes]]
_FetchResponse = tuple[str, list[tuple[bytes, bytes] | bytes]]
# mailbox name -> (LIST attributes, raw messages)
_Account = dict[str, tuple[str, list[bytes]]]


def _message(subject: str, message_id: str | None) -> bytes:
    headers = [
        "From: ivan@example.ru",
        "To: buh@example.ru",
        f"Subject: {subject}",
        "Date: Sat, 10 Oct 2026 12:00:00 +0300",
    ]
    if message_id:
        headers.append(f"Message-ID: {message_id}")
    return ("\r\n".join([*headers, "", f"Текст: {subject}", ""])).encode()


def _account() -> _Account:
    return {
        "INBOX": (
            "\\HasNoChildren",
            [
                _message("Счёт № 1", "<id-1@example.ru>"),
                _message("Без идентификатора", None),
            ],
        ),
        "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-": (
            "\\HasNoChildren \\Sent",
            [_message("Отправленное", "<id-2@example.ru>")],
        ),
        "Spam": ("\\HasNoChildren \\Junk", [_message("Спам", "<id-3@example.ru>")]),
    }


def _expand(message_set: str) -> Iterator[int]:
    for item in message_set.split(","):
        first, _, last = item.partition(":")
        yield from range(int(first), int(last or first) + 1)


class _FakeImap:
    def __init__(self, account: _Account, fail_fetch: bool = False) -> None:
        self._account = account
        self._fail_fetch = fail_fetch
        self._selected: list[bytes] = []
        self.logged_out = False

    def login(self, user: str, password: str) -> _Response:  # noqa: ARG002
        return _OK, [b""]

    def list(self, directory: str, pattern: str) -> _Response:  # noqa: ARG002
        return _OK, [
            f'({attributes}) "/" "{name}"'.encode()
            for name, (attributes, _messages) in self._account.items()
        ]

    def select(self, mailbox: str, readonly: bool) -> _Response:
        assert readonly
        self._selected = self._account[mailbox.strip('"')][1]
        return _OK, [str(len(self._selected)).encode()]

    def search(self, charset: None, criteria: str) -> _Response:  # noqa: ARG002
        ids = " ".join(str(i) for i in range(1, len(self._selected) + 1))
        return _OK, [ids.encode()]

    def fetch(self, message_set: str, message_parts: str) -> _FetchResponse:
        if self._fail_fetch:
            raise imaplib.IMAP4.abort("connection dropped")
        response: list[tuple[bytes, bytes] | bytes] = []
        for number in _expand(message_set):
            raw = self._selected[number - 1]
            if "HEADER.FIELDS" in message_parts:
                header = email.message_from_bytes(raw).get("Message-ID")
                body = f"Message-ID: {header}\r\n\r\n" if header else "\r\n"
                part = f"{number} (BODY[HEADER.FIELDS (MESSAGE-ID)] {{{len(body)}}}"
                response += [(part.encode(), body.encode()), b")"]
            else:
                part = f'{number} (INTERNALDATE "10-Oct-2026 12:00:00 +0300" RFC822 {{{len(raw)}}}'
                response += [(part.encode(), raw), b")"]
        return _OK, response

    def logout(self) -> _Response:
        self.logged_out = True
        return "BYE", [b""]


class _RejectingImap(_FakeImap):
    def login(self, user: str, password: str) -> _Response:  # noqa: ARG002
        raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] LOGIN invalid credentials")


class _Server:
    """Hands out one fake session per connection and remembers them all."""

    def __init__(self, account: _Account, fail_fetch: bool = False) -> None:
        self._account = account
        self._fail_fetch = fail_fetch
        self.sessions: list[_FakeImap] = []

    def __call__(self, **_kwargs: object) -> _FakeImap:
        session = _FakeImap(self._account, fail_fetch=self._fail_fetch)
        self.sessions.append(session)
        return session


def _with_credentials(connector: ImapConnector) -> ImapConnector:
    connector.set_credentials_provider(
        OnyxStaticCredentialsProvider(
            tenant_id=None,
            connector_name=DocumentSource.IMAP,
            credential_json={"imap_username": "u", "imap_password": "p"},
        )
    )
    return connector


def _full_run(connector: ImapConnector) -> list[Document]:
    documents: list[Document] = []
    checkpoint: ImapCheckpoint = connector.build_dummy_checkpoint()
    while checkpoint.has_more:
        generator = connector.load_from_checkpoint(0, 2_000_000_000, checkpoint)
        try:
            while True:
                item = next(generator)
                assert isinstance(item, Document), item
                documents.append(item)
        except StopIteration as stop:
            checkpoint = stop.value
    return documents


def _slim_ids(connector: ImapConnector) -> set[str]:
    return {
        document.id
        for batch in connector.retrieve_all_slim_docs()
        for document in batch
        if isinstance(document, SlimDocument)
    }


@patch("onyx.connectors.imap.connector.imaplib.IMAP4_SSL")
def test_every_session_of_a_full_run_is_logged_out(mock_imap4_ssl: MagicMock) -> None:
    server = _Server(_account())
    mock_imap4_ssl.side_effect = server

    _full_run(_with_credentials(ImapConnector(host="imap.example.com")))

    assert server.sessions
    assert all(session.logged_out for session in server.sessions)


@patch("onyx.connectors.imap.connector.imaplib.IMAP4_SSL")
def test_a_failed_step_still_logs_out(mock_imap4_ssl: MagicMock) -> None:
    server = _Server(_account(), fail_fetch=True)
    mock_imap4_ssl.side_effect = server

    with pytest.raises(imaplib.IMAP4.abort):
        _full_run(_with_credentials(ImapConnector(host="imap.example.com")))

    assert server.sessions
    assert all(session.logged_out for session in server.sessions)


@patch("onyx.connectors.imap.connector.imaplib.IMAP4_SSL")
def test_validation_logs_out(mock_imap4_ssl: MagicMock) -> None:
    server = _Server(_account())
    mock_imap4_ssl.side_effect = server

    _with_credentials(
        ImapConnector(host="imap.example.com")
    ).validate_connector_settings()

    assert [session.logged_out for session in server.sessions] == [True]


_CONNECTORS: list[Callable[[], ImapConnector]] = [
    lambda: ImapConnector(host="imap.example.com"),
    lambda: YandexMailConnector(),
    lambda: YandexMailConnector(mailboxes=["Отправленные"]),
]


@pytest.mark.parametrize(
    "make_connector",
    _CONNECTORS,
    ids=["imap-all-mailboxes", "preset-skips-spam", "preset-typed-folder"],
)
@patch("onyx.connectors.imap.connector.imaplib.IMAP4_SSL")
def test_slim_ids_match_the_full_run(
    mock_imap4_ssl: MagicMock, make_connector: Callable[[], ImapConnector]
) -> None:
    # Pruning deletes indexed ids the slim pass does not return (§5.3).
    mock_imap4_ssl.side_effect = _Server(_account())

    full_ids = {
        document.id for document in _full_run(_with_credentials(make_connector()))
    }
    slim_ids = _slim_ids(_with_credentials(make_connector()))

    assert slim_ids == full_ids
    assert slim_ids


@patch("onyx.connectors.imap.connector.imaplib.IMAP4_SSL")
def test_slim_reads_headers_and_hashes_a_message_without_an_id(
    mock_imap4_ssl: MagicMock,
) -> None:
    server = _Server(_account())
    mock_imap4_ssl.side_effect = server

    ids = _slim_ids(_with_credentials(YandexMailConnector()))

    assert "<id-1@example.ru>" in ids
    assert "<id-2@example.ru>" in ids
    assert "<id-3@example.ru>" not in ids
    assert len([i for i in ids if re.fullmatch(r"imap-sha256:[0-9a-f]{64}", i)]) == 1
    assert all(session.logged_out for session in server.sessions)


@patch("onyx.connectors.imap.connector.imaplib.IMAP4_SSL")
def test_documents_name_their_folder(mock_imap4_ssl: MagicMock) -> None:
    mock_imap4_ssl.side_effect = _Server(_account())

    texts = {
        document.semantic_identifier: document.get_text_content()
        for document in _full_run(_with_credentials(YandexMailConnector()))
    }

    assert "folder: INBOX" in texts["Счёт № 1"]
    # Listed in modified UTF-7, shown decoded.
    assert "folder: Отправленные" in texts["Отправленное"]


@patch("time.sleep")
@patch("onyx.connectors.imap.connector.imaplib.IMAP4_SSL")
def test_a_dropped_connection_is_retried(
    mock_imap4_ssl: MagicMock, _mock_sleep: MagicMock
) -> None:
    # Seen on the stand: Yandex closed the session right after the greeting.
    server = _Server(_account())
    mock_imap4_ssl.side_effect = [
        imaplib.IMAP4.abort("command: CAPABILITY => problems with connection"),
        server(),
    ]

    _with_credentials(YandexMailConnector()).validate_connector_settings()

    assert mock_imap4_ssl.call_count == 2
    assert [session.logged_out for session in server.sessions] == [True]


@patch("time.sleep")
@patch("onyx.connectors.imap.connector.imaplib.IMAP4_SSL")
def test_a_wrong_password_is_not_retried(
    mock_imap4_ssl: MagicMock, _mock_sleep: MagicMock
) -> None:
    session = _RejectingImap(_account())
    mock_imap4_ssl.return_value = session

    with pytest.raises(imaplib.IMAP4.error):
        _with_credentials(YandexMailConnector()).validate_connector_settings()

    assert mock_imap4_ssl.call_count == 1
    assert session.logged_out


@patch("onyx.connectors.imap.connector.imaplib.IMAP4_SSL")
def test_slim_raises_on_a_login_failure(mock_imap4_ssl: MagicMock) -> None:
    mock_imap4_ssl.return_value = _RejectingImap(_account())

    # Pruning deletes every indexed message when the slim pass yields nothing,
    # so an auth failure must raise (feature map: connectors §5.5).
    with pytest.raises(imaplib.IMAP4.error):
        _slim_ids(_with_credentials(YandexMailConnector()))
