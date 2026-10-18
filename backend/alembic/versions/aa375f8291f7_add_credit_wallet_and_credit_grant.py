"""add_credit_wallet_and_credit_grant

Revision ID: aa375f8291f7
Revises: 287021f3b46c
Create Date: 2026-09-12 07:05:35.946817

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "aa375f8291f7"
down_revision = "287021f3b46c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the LLM credit wallet and its grant ledger.

    Both tables live in the tenant schema — the wallet is read by the
    admission check on the managed-LLM hot path, so it must be local to the
    tenant, not an HTTP hop to the control plane.
    """
    op.create_table(
        "credit_wallet",
        sa.Column("id", sa.Integer(), primary_key=True),
        # The one money-ish field where fractional units are required:
        # per-call LLM cost is a fraction of a cent. Consumption in USD
        # cents, not our money — the name still carries the unit.
        sa.Column(
            "balance_cents",
            sa.Numeric(14, 4, asdecimal=False),
            nullable=False,
        ),
        # Scale of the usage indicator: sum of all accepted grants,
        # incremented in the same transaction as the ledger insert.
        sa.Column("total_granted_cents", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "credit_grant",
        # UUID issued by the control plane — the grant idempotency key.
        sa.Column("grant_id", sa.String(36), primary_key=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("source_payment_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("credit_grant")
    op.drop_table("credit_wallet")
