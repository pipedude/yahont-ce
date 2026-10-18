"""LLM credit wallet operations.

The wallet lives in the tenant schema and is read by the admission check
before every managed-LLM call. The balance changes ONLY through the grant
ledger: grants insert into ``credit_grant`` with an idempotency key
and increment the wallet in the same transaction; spends decrement it after
a model call. There is no direct balance UPDATE anywhere.
"""

from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.models import CreditGrant, CreditWallet
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_credit_wallet(db_session: Session) -> CreditWallet | None:
    """Read-only wallet lookup. A missing row means a zero balance — the
    tenant has never been granted credits."""
    return db_session.query(CreditWallet).filter(CreditWallet.id == 1).first()


def grant_credit_wallet(
    db_session: Session,
    grant_id: str,
    amount_cents: int,
    source_payment_id: str | None = None,
) -> tuple[bool, float, float]:
    """Idempotent credit grant.

    Inserts the ledger row with ``ON CONFLICT (grant_id) DO NOTHING``. A
    zero rowcount means the grant was already applied — returns
    ``(False, current, current)`` and touches nothing. Otherwise increments
    BOTH ``balance_cents`` and ``total_granted_cents`` in the same
    transaction, so the wallet and its ledger cannot drift.

    Returns ``(updated, old_balance, new_balance)`` so the caller can
    detect the balance crossing zero without a second read. The caller owns
    the transaction (commit/rollback).
    """
    now = datetime.now(timezone.utc)

    insert_stmt = pg_insert(CreditGrant).values(
        grant_id=grant_id,
        amount_cents=amount_cents,
        source_payment_id=source_payment_id,
        created_at=now,
    )
    result = db_session.execute(
        insert_stmt.on_conflict_do_nothing(index_elements=["grant_id"])
    )
    if result.rowcount == 0:  # ty: ignore[unresolved-attribute]
        logger.info("Credit grant %s already applied; skipping", grant_id)
        wallet = get_credit_wallet(db_session)
        current = wallet.balance_cents if wallet else 0.0
        return (False, current, current)

    wallet = get_credit_wallet(db_session)
    if wallet is None:
        wallet = CreditWallet(
            id=1,
            balance_cents=0,
            total_granted_cents=0,
            updated_at=now,
        )
        db_session.add(wallet)
        db_session.flush()

    old_balance = wallet.balance_cents
    wallet.balance_cents = old_balance + amount_cents
    wallet.total_granted_cents += amount_cents
    wallet.updated_at = now
    return (True, old_balance, wallet.balance_cents)


def spend_credit_wallet(
    db_session: Session, amount_cents: float
) -> tuple[float, float] | None:
    """Debit the wallet after a managed-LLM call.

    No ``balance >= amount`` guard on purpose: the message has already been
    sent, so an overdraft of at most one call is acceptable.
    A missing wallet row is a no-op returning None — tenants that never
    bought packages have nothing to spend.

    Returns ``(old_balance, new_balance)`` so the caller can detect the
    balance crossing zero without a second read. The caller owns the
    transaction.
    """
    wallet = get_credit_wallet(db_session)
    if wallet is None:
        return None

    old_balance = wallet.balance_cents
    wallet.balance_cents = old_balance - amount_cents
    wallet.updated_at = datetime.now(timezone.utc)
    return (old_balance, wallet.balance_cents)
