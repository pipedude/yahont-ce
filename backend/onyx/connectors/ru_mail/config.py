from onyx.connectors.connector_config import ConnectorConfig


class RuMailConnectorConfig(ConnectorConfig):
    """Shared by the Yandex Mail and Mail.ru presets: the server is fixed, so
    only the mailboxes are configurable."""

    mailboxes: list[str] | None = None
