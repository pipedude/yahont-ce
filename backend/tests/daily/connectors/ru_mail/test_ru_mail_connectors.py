"""Daily tests of the Yandex Mail and Mail.ru presets against real mailboxes.

Each provider needs a test mailbox with fixed content and two values, from the
process env or `.vscode/.env` (`uv run --env-file .vscode/.env pytest ...`):

- `YANDEX_MAIL_USERNAME` / `MAILRU_MAIL_USERNAME`: the login;
- `YANDEX_MAIL_APP_PASSWORD` / `MAILRU_MAIL_APP_PASSWORD`: the app password.

Seed each mailbox once:

1. Inbox: a message with the subject `REPLY_SUBJECT`, sent from an account
   whose display name is in Cyrillic.
2. A folder named `CYRILLIC_FOLDER` with one message, subject `FOLDER_SUBJECT`.
3. Spam: a message with the subject `SPAM_SUBJECT`. Trash: `TRASH_SUBJECT`.
   Providers purge Spam and Trash after some days; reseed them when
   `test_seed_messages_are_in_spam_and_trash` fails.
"""

import os
import time
from typing import NamedTuple

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.imap.connector import ImapConnector
from onyx.connectors.models import Document
from onyx.connectors.ru_mail.connector import MailruMailConnector, YandexMailConnector
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

REPLY_SUBJECT = (
    "Re: Проверка коннектора Yahont: счёт на оплату № 145 от 10 октября 2026 года"
)
CYRILLIC_FOLDER = "Проверка Yahont"
FOLDER_SUBJECT = "Yahont: письмо в папке на кириллице"
SPAM_SUBJECT = "Yahont: письмо в спаме"
TRASH_SUBJECT = "Yahont: письмо в корзине"


class _Provider(NamedTuple):
    connector_class: type[YandexMailConnector] | type[MailruMailConnector]
    source: DocumentSource
    host: str
    username_env: str
    password_secret: TestSecret


_YANDEX = _Provider(
    connector_class=YandexMailConnector,
    source=DocumentSource.YANDEX_MAIL,
    host="imap.yandex.ru",
    username_env="YANDEX_MAIL_USERNAME",
    password_secret=TestSecret.YANDEX_MAIL_APP_PASSWORD,
)
_MAILRU = _Provider(
    connector_class=MailruMailConnector,
    source=DocumentSource.MAILRU_MAIL,
    host="imap.mail.ru",
    username_env="MAILRU_MAIL_USERNAME",
    password_secret=TestSecret.MAILRU_MAIL_APP_PASSWORD,
)

# Each case asks only for its own provider's secret, so `-k yandex` runs
# without the Mail.ru password.
_PROVIDERS = [
    pytest.param(
        _YANDEX,
        marks=pytest.mark.secrets(TestSecret.YANDEX_MAIL_APP_PASSWORD),
        id="yandex",
    ),
    pytest.param(
        _MAILRU,
        marks=pytest.mark.secrets(TestSecret.MAILRU_MAIL_APP_PASSWORD),
        id="mailru",
    ),
]


def _load(
    connector: ImapConnector,
    provider: _Provider,
    test_secrets: dict[TestSecret, str],
) -> list[Document]:
    username = os.environ.get(provider.username_env)
    assert username, f"{provider.username_env} is not set"
    connector.set_credentials_provider(
        OnyxStaticCredentialsProvider(
            tenant_id=None,
            connector_name=provider.source,
            credential_json={
                "imap_username": username,
                "imap_password": test_secrets[provider.password_secret],
            },
        )
    )
    return load_all_from_connector(
        connector=connector, start=0, end=time.time()
    ).documents


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_seed_messages_are_in_spam_and_trash(
    provider: _Provider, test_secrets: dict[TestSecret, str]
) -> None:
    # Plain IMAP reads every mailbox: this proves the seed the preset must skip.
    documents = _load(ImapConnector(host=provider.host), provider, test_secrets)
    titles = {document.title for document in documents}

    assert SPAM_SUBJECT in titles, "reseed the Spam message (the provider purged it)"
    assert TRASH_SUBJECT in titles, "reseed the Trash message (the provider purged it)"


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_preset_indexes_every_mailbox_except_spam_and_trash(
    provider: _Provider, test_secrets: dict[TestSecret, str]
) -> None:
    documents = _load(provider.connector_class(), provider, test_secrets)
    titles = {document.title for document in documents}

    assert REPLY_SUBJECT in titles
    assert FOLDER_SUBJECT in titles
    assert SPAM_SUBJECT not in titles
    assert TRASH_SUBJECT not in titles
    assert {document.source for document in documents} == {provider.source}
    # The LLM, recency and time filters read the date from doc_updated_at.
    assert all(document.doc_updated_at for document in documents)


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_reply_subject_and_cyrillic_sender_are_kept_whole(
    provider: _Provider, test_secrets: dict[TestSecret, str]
) -> None:
    documents = _load(
        provider.connector_class(mailboxes=["INBOX"]), provider, test_secrets
    )
    reply = next(
        (document for document in documents if document.title == REPLY_SUBJECT),
        None,
    )

    assert reply is not None, f"no message titled {REPLY_SUBJECT!r} in INBOX"
    owners = reply.primary_owners or []
    assert owners
    assert all(owner.email and "@" in owner.email for owner in owners)
    assert any(
        owner.display_name and not owner.display_name.isascii() for owner in owners
    )


@pytest.mark.parametrize("provider", _PROVIDERS)
def test_cyrillic_folder_typed_by_hand_is_indexed(
    provider: _Provider, test_secrets: dict[TestSecret, str]
) -> None:
    documents = _load(
        provider.connector_class(mailboxes=[CYRILLIC_FOLDER]), provider, test_secrets
    )

    assert {document.title for document in documents} == {FOLDER_SUBJECT}
