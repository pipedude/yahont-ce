import email
from datetime import datetime, timezone
from email.header import Header
from unittest.mock import MagicMock

import pytest

from onyx.connectors.imap.connector import (
    _IMAP_OKAY_STATUS,
    _decode_mailbox_name,
    _fetch_all_mailboxes_for_email_account,
    _fetch_email_ids_in_mailbox,
    _sanitize_mailbox_names,
)
from onyx.connectors.imap.models import EmailHeaders

_LONG_SUBJECT = (
    "Счёт на оплату по договору поставки оборудования № 145 от 10 октября 2026 года"
)


def _parse(raw: str) -> EmailHeaders:
    return EmailHeaders.from_email_msg(email.message_from_string(raw))


def _raw_message(subject: str, sender: str) -> str:
    return (
        f"Subject: {subject}\r\n"
        f"From: {sender}\r\n"
        "To: buh@example.ru\r\n"
        "Date: Sat, 10 Oct 2026 12:00:00 +0300\r\n"
        "Message-ID: <id-1@example.ru>\r\n"
        "\r\n"
        "body\r\n"
    )


def _list_client(*lines: bytes) -> MagicMock:
    client = MagicMock()
    client.list.return_value = (_IMAP_OKAY_STATUS, list(lines))
    return client


def test_reply_subject_with_plain_prefix_is_decoded_whole() -> None:
    encoded = Header(_LONG_SUBJECT, "utf-8").encode()
    assert encoded.count("=?utf-8?") > 1

    headers = _parse(_raw_message(f"Re: {encoded}", "ivan@example.ru"))

    assert headers.subject == f"Re: {_LONG_SUBJECT}"


def test_sender_with_cyrillic_display_name_keeps_the_address() -> None:
    name = Header("Иван Петров", "utf-8").encode()

    headers = _parse(_raw_message("Test", f"{name} <ivan@example.ru>"))

    assert headers.sender == "Иван Петров <ivan@example.ru>"


def test_mailbox_discovery_skips_mailboxes_that_cannot_be_selected() -> None:
    client = _list_client(
        b'(\\HasNoChildren) "|" INBOX',
        b'(\\Noselect \\HasChildren) "|" Archive',
        b'(\\NonExistent) "|" Gone',
        b'(\\HasNoChildren \\Junk) "|" Spam',
    )

    mailboxes = _fetch_all_mailboxes_for_email_account(
        mail_client=client, skip_junk_and_trash=False
    )

    assert mailboxes == ["INBOX", "Spam"]


def test_mailbox_discovery_skips_junk_and_trash_when_asked() -> None:
    client = _list_client(
        b'(\\HasNoChildren) "/" INBOX',
        b'(\\HasNoChildren \\Junk) "/" "&BCEEPwQwBDw-"',
        b'(\\HasNoChildren \\Trash) "/" "&BBoEPgRABDcEOAQ9BDA-"',
        b'(\\HasNoChildren \\Sent) "/" "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-"',
    )

    mailboxes = _fetch_all_mailboxes_for_email_account(
        mail_client=client, skip_junk_and_trash=True
    )

    assert mailboxes == ["INBOX", "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-"]


def test_mailbox_discovery_skips_the_mailru_spam_flag() -> None:
    # Seen on the stand: Mail.ru flags its spam folder `\Spam`, not `\Junk`.
    client = _list_client(
        b'(\\Inbox) "/" "INBOX"',
        b'(\\Spam) "/" "&BCEEPwQwBDw-"',
        b'(\\Trash) "/" "&BBoEPgRABDcEOAQ9BDA-"',
        b'(\\Sent) "/" "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-"',
        b'() "/" "INBOX/Social"',
    )

    mailboxes = _fetch_all_mailboxes_for_email_account(
        mail_client=client, skip_junk_and_trash=True
    )

    assert mailboxes == [
        "INBOX",
        "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-",
        "INBOX/Social",
    ]


def test_cyrillic_mailbox_names_are_encoded_to_modified_utf7() -> None:
    assert _sanitize_mailbox_names(["Отправленные"]) == [
        '"&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-"'
    ]
    assert _sanitize_mailbox_names(["Работа & отчёты"]) == [
        '"&BCAEMAQxBD4EQgQw- &- &BD4EQgRHBFEEQgRL-"'
    ]


@pytest.mark.parametrize(
    ("start", "end", "criteria"),
    [
        # A 30-minute poll window inside one day must still see that day's mail.
        (
            datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 10, 11, 9, 30, tzinfo=timezone.utc),
            '(SINCE "11-Oct-2026" BEFORE "12-Oct-2026")',
        ),
        (
            datetime(2026, 10, 31, 23, 0, tzinfo=timezone.utc),
            datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc),
            '(SINCE "31-Oct-2026" BEFORE "01-Nov-2026")',
        ),
    ],
)
def test_search_window_includes_the_day_of_the_window_end(
    start: datetime, end: datetime, criteria: str
) -> None:
    client = MagicMock()
    client.select.return_value = (_IMAP_OKAY_STATUS, [b"2"])
    client.search.return_value = (_IMAP_OKAY_STATUS, [b"1 2"])

    email_ids = _fetch_email_ids_in_mailbox(
        mail_client=client,
        mailbox='"INBOX"',
        start=start.timestamp(),
        end=end.timestamp(),
    )

    client.search.assert_called_once_with(None, criteria)
    assert email_ids == ["1", "2"]


def test_a_window_without_a_start_sends_no_since_condition() -> None:
    # Seen on the stand: Mail.ru answers `SINCE "01-Jan-1970"` with nothing,
    # so the first run (start = 0) found no mail. Yandex accepts that date.
    client = MagicMock()
    client.select.return_value = (_IMAP_OKAY_STATUS, [b"3"])
    client.search.return_value = (_IMAP_OKAY_STATUS, [b"1 2 3"])

    email_ids = _fetch_email_ids_in_mailbox(
        mail_client=client,
        mailbox='"INBOX"',
        start=0,
        end=datetime(2026, 10, 11, 9, 30, tzinfo=timezone.utc).timestamp(),
    )

    client.search.assert_called_once_with(None, 'BEFORE "12-Oct-2026"')
    assert email_ids == ["1", "2", "3"]


@pytest.mark.parametrize(
    ("mailbox", "name"),
    [
        ('"&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-"', "Отправленные"),
        ('"INBOX"', "INBOX"),
        ('"Drafts|template"', "Drafts|template"),
        ('"R&-D"', "R&D"),
        # Not valid modified UTF-7: shown as listed, not dropped.
        ('"R&D-team"', "R&D-team"),
    ],
)
def test_mailbox_names_are_decoded_for_display(mailbox: str, name: str) -> None:
    assert _decode_mailbox_name(mailbox) == name


def test_decoding_reverses_encoding() -> None:
    for name in ["Отправленные", "Проверка Yahont", "Счета/2026", "Входящие & Ко"]:
        assert _decode_mailbox_name(_sanitize_mailbox_names([name])[0]) == name


def test_ascii_mailbox_names_are_left_as_is() -> None:
    assert _sanitize_mailbox_names(
        ["INBOX", "R&D", "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-", ""]
    ) == ['"INBOX"', '"R&D"', '"&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-"']
