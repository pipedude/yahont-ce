"""IMAP presets for Russian mail providers.

Both providers serve IMAP over SSL on port 993 and accept only an app password.
Spam and Trash are skipped when mailboxes are discovered automatically.
"""

from onyx.configs.constants import DocumentSource
from onyx.connectors.imap.connector import ImapConnector

_IMAP_SSL_PORT = 993


class YandexMailConnector(ImapConnector):
    _source = DocumentSource.YANDEX_MAIL
    _skip_junk_and_trash = True

    def __init__(self, mailboxes: list[str] | None = None) -> None:
        # `imap.ya.ru` is only for clients outside Russia; the cloud is in Russia.
        super().__init__(
            host="imap.yandex.ru", port=_IMAP_SSL_PORT, mailboxes=mailboxes
        )


class MailruMailConnector(ImapConnector):
    _source = DocumentSource.MAILRU_MAIL
    _skip_junk_and_trash = True

    def __init__(self, mailboxes: list[str] | None = None) -> None:
        # Also serves @inbox.ru, @list.ru, @bk.ru and @internet.ru.
        super().__init__(host="imap.mail.ru", port=_IMAP_SSL_PORT, mailboxes=mailboxes)
