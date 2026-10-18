"""Money gate for image captioning on indexing.

``get_default_llm_with_vision()`` resolves whichever model is pinned as the
tenant's vision default, regardless of who pays for it. For a BYOK provider
that is fine: the tenant's own key, the tenant's own money. For the managed
``yahont`` provider the platform's wallet pays, and nothing checked whether
the tenant could still afford the call before summarizing every image in a
batch.

This module adds that check in front of ``get_default_llm_with_vision()``.
A refusal here never fails the document: the caller just skips image
summarization for this batch, the same as when no vision model is
configured at all — the rest of the document still indexes normally.
"""

from enum import Enum

from sqlalchemy.orm import Session

from onyx.db.credit_wallet import get_credit_wallet
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.llm import reset_default_vision_if_yahont
from onyx.db.usage import UsageType
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.factory import get_default_llm_with_vision
from onyx.llm.interfaces import LLM
from onyx.server.manage.llm.provider_cache import (
    invalidate_provider_listing_cache,
)
from onyx.server.usage_limits import (
    check_usage_and_raise,
    is_onyx_managed_api_key,
    is_tenant_on_trial_fn,
    is_usage_limits_enabled,
)
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


class _SpendCheck(Enum):
    ALLOWED = "allowed"
    # Trial quota exhausted: the weekly window resets on its own, so the
    # default is left alone — clearing it would just make the admin re-pick
    # the same model next week for no reason.
    BLOCKED_TRIAL = "blocked_trial"
    # No active credit package (or an empty one): the platform stops paying
    # for captioning until the admin picks a model again.
    BLOCKED_NO_PACKAGE = "blocked_no_package"
    # The check itself failed (DB, cache, control plane) — skip this batch,
    # but a transient error must never clear a tenant's own choice.
    CHECK_FAILED = "check_failed"


def _check_spend(tenant_id: str, db_session: Session) -> _SpendCheck:
    if is_tenant_on_trial_fn(tenant_id):
        if not is_usage_limits_enabled():
            return _SpendCheck.ALLOWED
        try:
            check_usage_and_raise(
                db_session=db_session,
                usage_type=UsageType.LLM_COST,
                tenant_id=tenant_id,
                pending_amount=0,  # checking current usage, not a pending call
            )
        except OnyxError:
            return _SpendCheck.BLOCKED_TRIAL
        except Exception:
            logger.exception(
                "Trial LLM-cost check failed for tenant %s — skipping image "
                "captioning for this batch",
                tenant_id,
            )
            return _SpendCheck.CHECK_FAILED
        return _SpendCheck.ALLOWED

    # Not on trial: the credit wallet is the only money gate (the weekly
    # monetary quota is zero by design for paid tenants).
    # Read directly, not via `check_wallet_admission`: that helper raises and
    # refuses a chat request, while captioning must degrade — skip the call
    # and, with no package, clear the default. Both treat a missing wallet
    # row as a zero balance: nothing was ever bought.
    try:
        wallet = get_credit_wallet(db_session)
    except Exception:
        logger.exception(
            "Credit wallet read failed for tenant %s — skipping image "
            "captioning for this batch",
            tenant_id,
        )
        return _SpendCheck.CHECK_FAILED
    if wallet is not None and wallet.balance_cents > 0:
        return _SpendCheck.ALLOWED
    return _SpendCheck.BLOCKED_NO_PACKAGE


def get_vision_llm_for_image_summarization() -> LLM | None:
    """The vision LLM to summarize images with, or ``None`` to skip
    captioning for this batch.

    Behaves exactly like ``get_default_llm_with_vision()`` when there is no
    default, or when the default is a BYOK provider — the tenant's own key
    is never gated here. For the managed ``yahont`` provider, this
    additionally checks whether the tenant can still afford the call. On
    refusal it logs a warning and, for a non-trial tenant with no package,
    clears the default so the admin sees the "no model chosen" banner on
    Language Models instead of the platform silently continuing to pay.
    """
    llm = get_default_llm_with_vision()
    if llm is None:
        return None
    if not is_onyx_managed_api_key(llm.config.api_key):
        return llm
    # Packages and the wallet exist on cloud only; a self-hosted default key
    # has nothing to be checked against.
    if not MULTI_TENANT:
        return llm

    tenant_id = get_current_tenant_id()
    with get_session_with_current_tenant() as db_session:
        result = _check_spend(tenant_id, db_session)
        if result is _SpendCheck.ALLOWED:
            return llm

        if result is _SpendCheck.BLOCKED_NO_PACKAGE:
            if reset_default_vision_if_yahont(db_session):
                # The user-facing /llm/provider listing is Redis-cached (600 s)
                # and holds the cleared model in `default_vision` — without this
                # the Index Settings picker keeps showing a model that no longer
                # is the default. The admin listing is not cached and already
                # shows the reset.
                invalidate_provider_listing_cache()

        logger.warning(
            "Image captioning skipped for this batch: managed vision model "
            "spend check returned %s (tenant=%s)",
            result.value,
            tenant_id,
        )
        return None
