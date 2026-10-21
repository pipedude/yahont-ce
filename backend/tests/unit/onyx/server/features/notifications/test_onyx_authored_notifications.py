from unittest.mock import MagicMock, patch

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from onyx.db.models import Notification
from onyx.db.notification import _notification_filters
from onyx.server.features.notifications import api as notifications_api

API_MODULE = "onyx.server.features.notifications.api"
DB_MODULE = "onyx.db.notification"


def _run_create_checks() -> dict[str, MagicMock]:
    mocks = {
        name: MagicMock()
        for name in (
            "ensure_build_mode_intro_notification",
            "ensure_permissions_migration_notification",
            "ensure_release_notes_fresh_and_notify",
        )
    }
    with (
        patch(
            f"{API_MODULE}.ensure_build_mode_intro_notification",
            mocks["ensure_build_mode_intro_notification"],
        ),
        patch(
            f"{API_MODULE}.ensure_permissions_migration_notification",
            mocks["ensure_permissions_migration_notification"],
        ),
        patch(
            f"{API_MODULE}.ensure_release_notes_fresh_and_notify",
            mocks["ensure_release_notes_fresh_and_notify"],
        ),
    ):
        notifications_api._check_for_notifications_to_create(MagicMock(), MagicMock())
    return mocks


def _filters_sql() -> str:
    query = select(Notification.id).where(*_notification_filters(user=None))
    return str(query.compile(dialect=postgresql.dialect()))


def test_onyx_authored_notifications_are_not_created_by_default() -> None:
    with patch(f"{API_MODULE}.ENABLE_ONYX_NOTIFICATIONS", False):
        mocks = _run_create_checks()

    mocks["ensure_release_notes_fresh_and_notify"].assert_not_called()
    mocks["ensure_permissions_migration_notification"].assert_not_called()
    mocks["ensure_build_mode_intro_notification"].assert_called_once()


def test_onyx_authored_notifications_are_created_when_enabled() -> None:
    with patch(f"{API_MODULE}.ENABLE_ONYX_NOTIFICATIONS", True):
        mocks = _run_create_checks()

    mocks["ensure_release_notes_fresh_and_notify"].assert_called_once()
    mocks["ensure_permissions_migration_notification"].assert_called_once()
    mocks["ensure_build_mode_intro_notification"].assert_called_once()


def test_existing_onyx_authored_rows_are_hidden_when_disabled() -> None:
    with patch(f"{DB_MODULE}.ENABLE_ONYX_NOTIFICATIONS", False):
        sql = _filters_sql()

    assert "notification.notif_type !=" in sql
    assert "permissions_migration_v1" in sql or "notification.additional_data" in sql


def test_existing_rows_stay_visible_when_enabled() -> None:
    with patch(f"{DB_MODULE}.ENABLE_ONYX_NOTIFICATIONS", True):
        sql = _filters_sql()

    assert "notification.notif_type !=" not in sql
    assert "additional_data" not in sql
