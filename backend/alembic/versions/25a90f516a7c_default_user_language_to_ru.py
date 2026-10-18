"""default user language to ru

Revision ID: 25a90f516a7c
Revises: 7e351d53fc38
Create Date: 2026-09-26 21:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "25a90f516a7c"
down_revision = "7e351d53fc38"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "user",
        "language",
        existing_type=sa.String(),
        server_default="ru",
    )


def downgrade() -> None:
    op.alter_column(
        "user",
        "language",
        existing_type=sa.String(),
        server_default="en",
    )
