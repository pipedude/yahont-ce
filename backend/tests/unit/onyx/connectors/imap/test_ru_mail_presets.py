from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.imap.connector import _IMAP_OKAY_STATUS, ImapConnector
from onyx.connectors.models import Document
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.connectors.ru_mail.connector import MailruMailConnector, YandexMailConnector

_RAW_MESSAGE = (
    b"Subject: Hello\r\n"
    b"From: ivan@example.ru\r\n"
    b"To: buh@example.ru\r\n"
    b"Date: Sat, 10 Oct 2026 12:00:00 +0300\r\n"
    b"Message-ID: <id-1@example.ru>\r\n"
    b"\r\n"
    b"body\r\n"
)


def _with_credentials(connector: ImapConnector) -> ImapConnector:
    connector.set_credentials_provider(
        OnyxStaticCredentialsProvider(
            tenant_id=None,
            connector_name=DocumentSource.IMAP,
            credential_json={
                "imap_username": "ivan@example.ru",
                "imap_password": "app-password",
            },
        )
    )
    return connector


@pytest.mark.parametrize(
    ("connector_class", "source", "host"),
    [
        (YandexMailConnector, DocumentSource.YANDEX_MAIL, "imap.yandex.ru"),
        (MailruMailConnector, DocumentSource.MAILRU_MAIL, "imap.mail.ru"),
    ],
)
@patch("onyx.connectors.imap.connector.imaplib.IMAP4_SSL")
def test_preset_connects_to_its_server_and_tags_documents(
    mock_imap4_ssl: MagicMock,
    connector_class: type[YandexMailConnector] | type[MailruMailConnector],
    source: DocumentSource,
    host: str,
) -> None:
    client = mock_imap4_ssl.return_value
    client.login.return_value = (_IMAP_OKAY_STATUS, [b""])
    client.select.return_value = (_IMAP_OKAY_STATUS, [b"1"])
    client.search.return_value = (_IMAP_OKAY_STATUS, [b"1"])
    client.fetch.return_value = (_IMAP_OKAY_STATUS, [(b"1 (RFC822)", _RAW_MESSAGE)])
    connector = _with_credentials(connector_class(mailboxes=["INBOX"]))

    checkpoint = connector.build_dummy_checkpoint()
    for _ in range(2):
        generator = connector.load_from_checkpoint(0, 2_000_000_000, checkpoint)
        documents = []
        try:
            while True:
                documents.append(next(generator))
        except StopIteration as stop:
            checkpoint = stop.value

    assert mock_imap4_ssl.call_args.kwargs["host"] == host
    assert mock_imap4_ssl.call_args.kwargs["port"] == 993
    assert [
        document.source for document in documents if isinstance(document, Document)
    ] == [source]
    assert len(documents) == 1


def test_imap_connector_keeps_the_imap_source() -> None:
    assert ImapConnector(host="imap.example.com")._source == DocumentSource.IMAP


def test_presets_skip_junk_and_trash_but_plain_imap_does_not() -> None:
    assert YandexMailConnector()._skip_junk_and_trash
    assert MailruMailConnector()._skip_junk_and_trash
    assert not ImapConnector(host="imap.example.com")._skip_junk_and_trash


@pytest.mark.parametrize(
    ("source", "class_name"),
    [
        (DocumentSource.YANDEX_MAIL, "YandexMailConnector"),
        (DocumentSource.MAILRU_MAIL, "MailruMailConnector"),
    ],
)
def test_presets_are_registered(source: DocumentSource, class_name: str) -> None:
    mapping = CONNECTOR_CLASS_MAP[source]

    assert mapping.module_path == "onyx.connectors.ru_mail.connector"
    assert mapping.class_name == class_name
    assert set(mapping.config_class.model_fields) == {"mailboxes"}
