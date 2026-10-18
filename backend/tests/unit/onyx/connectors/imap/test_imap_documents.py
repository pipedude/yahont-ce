"""IMAP messages become documents the way Gmail threads do (gmail/connector.py:
`thread_to_document`): dates, header lines in the text, sender as the primary
owner, recipients as secondary owners, and a failure per message instead of a
failed run."""

import email
from datetime import datetime, timezone
from email.header import Header
from unittest.mock import MagicMock, patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.imap.connector import (
    _IMAP_OKAY_STATUS,
    _email_to_document,
    _fetch_email,
    _FetchedEmail,
)
from onyx.connectors.models import ConnectorFailure, Document

_SENDER = f"{Header('Иван Петров', 'utf-8').encode()} <ivan@example.ru>"


def _raw(*headers: str, body: str = "Добрый день, счёт во вложении.") -> bytes:
    lines = [*headers, "Content-Type: text/plain; charset=utf-8", "", body, ""]
    return "\r\n".join(lines).encode()


def _document(raw: bytes, internal_date: datetime | None = None) -> Document:
    result = _email_to_document(
        _FetchedEmail(
            message=email.message_from_bytes(raw),
            raw=raw,
            internal_date=internal_date,
        ),
        include_perm_sync=False,
        source=DocumentSource.YANDEX_MAIL,
    )
    assert isinstance(result, Document), result
    return result


_FULL_HEADERS = (
    f"From: {_SENDER}",
    "To: buh@example.ru",
    "Cc: director@example.ru",
    "Subject: Счёт № 145",
    "Date: Sat, 10 Oct 2026 12:00:00 +0300",
    "Message-ID: <id-1@example.ru>",
)


def test_dates_come_from_the_date_header() -> None:
    document = _document(_raw(*_FULL_HEADERS))

    sent_at = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)
    assert document.doc_updated_at == sent_at
    assert document.doc_created_at == sent_at


def test_missing_date_falls_back_to_the_server_receive_time() -> None:
    received_at = datetime(2026, 10, 11, 7, 0, tzinfo=timezone.utc)
    headers = [h for h in _FULL_HEADERS if not h.startswith("Date:")]

    document = _document(_raw(*headers), internal_date=received_at)

    assert document.doc_updated_at == received_at


def test_sender_is_the_primary_owner_and_recipients_are_secondary() -> None:
    document = _document(_raw(*_FULL_HEADERS))

    assert [(o.display_name, o.email) for o in document.primary_owners or []] == [
        ("Иван Петров", "ivan@example.ru")
    ]
    assert {o.email for o in document.secondary_owners or []} == {
        "buh@example.ru",
        "director@example.ru",
    }


def test_header_lines_are_added_to_the_text() -> None:
    document = _document(_raw(*_FULL_HEADERS))
    text = document.get_text_content()

    assert "Добрый день, счёт во вложении." in text
    assert "from: Иван Петров <ivan@example.ru>" in text
    assert "to: buh@example.ru" in text
    assert "cc: director@example.ru" in text
    assert "subject: Счёт № 145" in text


def test_raw_utf8_subject_is_not_garbled() -> None:
    # Some senders put raw UTF-8 into headers instead of encoded words.
    document = _document(_raw(*_FULL_HEADERS))

    assert document.semantic_identifier == "Счёт № 145"


def test_quoted_name_with_a_comma_stays_one_recipient() -> None:
    headers = [h for h in _FULL_HEADERS if not h.startswith("To:")]
    headers.append('To: "Петрова, Анна" <anna@example.ru>, buh@example.ru')

    document = _document(_raw(*headers))

    assert {(o.display_name, o.email) for o in document.secondary_owners or []} == {
        ("Петрова, Анна", "anna@example.ru"),
        ("", "buh@example.ru"),
        ("", "director@example.ru"),
    }


def test_message_without_a_sender_is_still_indexed() -> None:
    headers = [h for h in _FULL_HEADERS if not h.startswith("From:")]

    document = _document(_raw(*headers))

    assert document.primary_owners == []
    assert {o.email for o in document.secondary_owners or []} == {
        "buh@example.ru",
        "director@example.ru",
    }


def test_message_without_a_message_id_gets_a_stable_id() -> None:
    raw = _raw(*[h for h in _FULL_HEADERS if not h.startswith("Message-ID:")])

    first, second = _document(raw), _document(raw)

    assert first.id.startswith("imap-sha256:")
    assert first.id == second.id


def test_plain_text_wins_and_attachments_are_skipped() -> None:
    raw = (
        "\r\n".join(
            [
                *_FULL_HEADERS,
                'Content-Type: multipart/mixed; boundary="b"',
                "",
                "--b",
                "Content-Type: text/plain; charset=utf-8",
                'Content-Disposition: attachment; filename="log.txt"',
                "",
                "текст вложения",
                "--b",
                "Content-Type: text/html; charset=utf-8",
                "",
                "<p>HTML-версия</p>",
                "--b",
                "Content-Type: text/plain; charset=utf-8",
                "",
                "Текстовая версия",
                "--b--",
                "",
            ]
        )
    ).encode()

    text = _document(raw).get_text_content()

    assert "Текстовая версия" in text
    assert "HTML-версия" not in text
    assert "текст вложения" not in text


def test_a_broken_message_yields_a_failure_instead_of_failing_the_run() -> None:
    raw = _raw(*_FULL_HEADERS)

    with patch(
        "onyx.connectors.imap.connector._parse_email_body",
        side_effect=ValueError("broken"),
    ):
        result = _email_to_document(
            _FetchedEmail(
                message=email.message_from_bytes(raw), raw=raw, internal_date=None
            ),
            include_perm_sync=False,
            source=DocumentSource.YANDEX_MAIL,
        )

    assert isinstance(result, ConnectorFailure)
    assert result.failed_document is not None
    assert result.failed_document.document_id == "<id-1@example.ru>"


def test_fetch_reads_the_server_receive_time() -> None:
    raw = _raw(*_FULL_HEADERS)
    client = MagicMock()
    client.fetch.return_value = (
        _IMAP_OKAY_STATUS,
        [(b'7 (INTERNALDATE " 1-Oct-2026 10:00:00 +0300" RFC822 {123}', raw)],
    )

    fetched = _fetch_email(mail_client=client, email_id="7")

    client.fetch.assert_called_once_with(
        message_set="7", message_parts="(INTERNALDATE RFC822)"
    )
    assert fetched is not None
    assert fetched.raw == raw
    assert fetched.internal_date == datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc)
