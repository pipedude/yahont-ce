from typing import Annotated

from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class RuMailConnectorConfig(ConnectorConfig):
    """Shared by the Yandex Mail and Mail.ru presets: the server is fixed, so
    only the mailboxes are configurable."""

    # Same policy as the IMAP connector: an empty list means every mailbox.
    mailboxes: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
