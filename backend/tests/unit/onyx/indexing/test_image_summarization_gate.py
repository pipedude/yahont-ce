"""Money gate for image captioning on indexing.

Covers the decision table:
- no default / BYOK default -> untouched, no spend check at all.
- managed (`yahont`) default:
  - trial, quota available -> allowed.
  - trial, quota exhausted -> blocked, default left alone (resets on its
    own next week).
  - not trial, wallet has a positive balance -> allowed.
  - not trial, no wallet row or a non-positive balance -> blocked AND the
    default is cleared (no package was ever bought; the admin needs to
    pick a model again rather than silently keep paying).
  - the check itself failing (DB/cache error) -> blocked, default left
    alone (a transient error must never erase a tenant's own choice).
"""

from contextlib import ExitStack, nullcontext
from unittest.mock import MagicMock, patch

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.indexing.image_summarization_gate import (
    get_vision_llm_for_image_summarization,
)

_PATCH_PREFIX = "onyx.indexing.image_summarization_gate"


def _llm(api_key: str | None) -> MagicMock:
    llm = MagicMock()
    llm.config.api_key = api_key
    return llm


def test_no_default_vision_model_short_circuits() -> None:
    with (
        patch(f"{_PATCH_PREFIX}.get_default_llm_with_vision", return_value=None),
        patch(f"{_PATCH_PREFIX}.is_onyx_managed_api_key") as is_managed,
    ):
        assert get_vision_llm_for_image_summarization() is None

    is_managed.assert_not_called()


def test_byok_default_is_never_spend_checked() -> None:
    llm = _llm("tenants-own-key")
    with (
        patch(f"{_PATCH_PREFIX}.get_default_llm_with_vision", return_value=llm),
        patch(
            f"{_PATCH_PREFIX}.is_onyx_managed_api_key", return_value=False
        ) as is_managed,
        patch(f"{_PATCH_PREFIX}.is_tenant_on_trial_fn") as is_trial,
    ):
        result = get_vision_llm_for_image_summarization()

    assert result is llm
    is_managed.assert_called_once_with("tenants-own-key")
    is_trial.assert_not_called()


def test_self_hosted_has_no_wallet_so_nothing_is_gated() -> None:
    """Self-hosted has no packages and no wallet. An operator-set default key
    counts as "managed" for usage accounting, but the wallet gate must not
    refuse it or clear the tenant's default there."""
    llm = _llm("operator-default-key")
    with (
        patch(f"{_PATCH_PREFIX}.MULTI_TENANT", False),
        patch(f"{_PATCH_PREFIX}.get_default_llm_with_vision", return_value=llm),
        patch(f"{_PATCH_PREFIX}.is_onyx_managed_api_key", return_value=True),
        patch(f"{_PATCH_PREFIX}.get_credit_wallet") as get_wallet,
        patch(f"{_PATCH_PREFIX}.reset_default_vision_if_yahont") as reset_default,
    ):
        result = get_vision_llm_for_image_summarization()

    assert result is llm
    get_wallet.assert_not_called()
    reset_default.assert_not_called()


def _enter_managed_env(stack: ExitStack, *, is_trial: bool) -> MagicMock:
    """Common patches for a managed (yahont) default, parameterized on trial
    status. Entered on the caller's ExitStack so each test can layer its own
    trial/wallet-specific patches and spies on top."""
    llm = _llm("managed-key")
    stack.enter_context(patch(f"{_PATCH_PREFIX}.MULTI_TENANT", True))
    stack.enter_context(
        patch(f"{_PATCH_PREFIX}.get_default_llm_with_vision", return_value=llm)
    )
    stack.enter_context(
        patch(f"{_PATCH_PREFIX}.is_onyx_managed_api_key", return_value=True)
    )
    stack.enter_context(
        patch(f"{_PATCH_PREFIX}.get_current_tenant_id", return_value="tenant_x")
    )
    stack.enter_context(
        patch(
            f"{_PATCH_PREFIX}.get_session_with_current_tenant",
            return_value=nullcontext(MagicMock()),
        )
    )
    stack.enter_context(
        patch(f"{_PATCH_PREFIX}.is_tenant_on_trial_fn", return_value=is_trial)
    )
    return llm


def test_trial_allowed_within_quota() -> None:
    with ExitStack() as stack:
        llm = _enter_managed_env(stack, is_trial=True)
        stack.enter_context(
            patch(f"{_PATCH_PREFIX}.is_usage_limits_enabled", return_value=True)
        )
        check_usage = stack.enter_context(
            patch(f"{_PATCH_PREFIX}.check_usage_and_raise")
        )
        reset_default = stack.enter_context(
            patch(f"{_PATCH_PREFIX}.reset_default_vision_if_yahont")
        )

        result = get_vision_llm_for_image_summarization()

    assert result is llm
    check_usage.assert_called_once()
    reset_default.assert_not_called()


def test_trial_skipped_when_usage_limits_disabled() -> None:
    """USAGE_LIMITS_ENABLED=false means the weekly quota isn't enforced at
    all — the trial branch must not even attempt the DB check."""
    with ExitStack() as stack:
        llm = _enter_managed_env(stack, is_trial=True)
        stack.enter_context(
            patch(f"{_PATCH_PREFIX}.is_usage_limits_enabled", return_value=False)
        )
        check_usage = stack.enter_context(
            patch(f"{_PATCH_PREFIX}.check_usage_and_raise")
        )
        reset_default = stack.enter_context(
            patch(f"{_PATCH_PREFIX}.reset_default_vision_if_yahont")
        )

        result = get_vision_llm_for_image_summarization()

    assert result is llm
    check_usage.assert_not_called()
    reset_default.assert_not_called()


def test_trial_quota_exhausted_blocks_without_resetting_default() -> None:
    with ExitStack() as stack:
        _enter_managed_env(stack, is_trial=True)
        stack.enter_context(
            patch(f"{_PATCH_PREFIX}.is_usage_limits_enabled", return_value=True)
        )
        stack.enter_context(
            patch(
                f"{_PATCH_PREFIX}.check_usage_and_raise",
                side_effect=OnyxError(OnyxErrorCode.RATE_LIMITED),
            )
        )
        reset_default = stack.enter_context(
            patch(f"{_PATCH_PREFIX}.reset_default_vision_if_yahont")
        )
        invalidate_cache = stack.enter_context(
            patch(f"{_PATCH_PREFIX}.invalidate_provider_listing_cache")
        )

        result = get_vision_llm_for_image_summarization()

    assert result is None
    # The weekly window resets on its own — clearing the default would just
    # make the admin re-pick the same model next week for no reason.
    reset_default.assert_not_called()
    invalidate_cache.assert_not_called()


def test_trial_check_error_blocks_without_resetting_default() -> None:
    """A transient failure in the check itself (not a real quota hit) must
    never clear the tenant's own choice."""
    with ExitStack() as stack:
        _enter_managed_env(stack, is_trial=True)
        stack.enter_context(
            patch(f"{_PATCH_PREFIX}.is_usage_limits_enabled", return_value=True)
        )
        stack.enter_context(
            patch(
                f"{_PATCH_PREFIX}.check_usage_and_raise",
                side_effect=RuntimeError("db down"),
            )
        )
        reset_default = stack.enter_context(
            patch(f"{_PATCH_PREFIX}.reset_default_vision_if_yahont")
        )

        result = get_vision_llm_for_image_summarization()

    assert result is None
    reset_default.assert_not_called()


def test_paid_allowed_with_positive_balance() -> None:
    with ExitStack() as stack:
        llm = _enter_managed_env(stack, is_trial=False)
        wallet = MagicMock(balance_cents=150)
        stack.enter_context(
            patch(f"{_PATCH_PREFIX}.get_credit_wallet", return_value=wallet)
        )
        reset_default = stack.enter_context(
            patch(f"{_PATCH_PREFIX}.reset_default_vision_if_yahont")
        )

        result = get_vision_llm_for_image_summarization()

    assert result is llm
    reset_default.assert_not_called()


def test_paid_no_wallet_row_blocks_and_resets_default() -> None:
    """No wallet row means no package was ever bought — a zero balance, the
    common case for a tenant that never purchased LLM credits (same rule as
    `check_wallet_admission`)."""
    with ExitStack() as stack:
        _enter_managed_env(stack, is_trial=False)
        stack.enter_context(
            patch(f"{_PATCH_PREFIX}.get_credit_wallet", return_value=None)
        )
        reset_default = stack.enter_context(
            patch(
                f"{_PATCH_PREFIX}.reset_default_vision_if_yahont",
                return_value=True,
            )
        )
        invalidate_cache = stack.enter_context(
            patch(f"{_PATCH_PREFIX}.invalidate_provider_listing_cache")
        )

        result = get_vision_llm_for_image_summarization()

    assert result is None
    reset_default.assert_called_once()
    # The user-facing /llm/provider listing is cached — without invalidation
    # the Index Settings picker keeps showing the cleared default for up to
    # 10 minutes.
    invalidate_cache.assert_called_once()


def test_paid_empty_wallet_blocks_and_resets_default() -> None:
    with ExitStack() as stack:
        _enter_managed_env(stack, is_trial=False)
        wallet = MagicMock(balance_cents=0)
        stack.enter_context(
            patch(f"{_PATCH_PREFIX}.get_credit_wallet", return_value=wallet)
        )
        reset_default = stack.enter_context(
            patch(
                f"{_PATCH_PREFIX}.reset_default_vision_if_yahont",
                return_value=True,
            )
        )
        invalidate_cache = stack.enter_context(
            patch(f"{_PATCH_PREFIX}.invalidate_provider_listing_cache")
        )

        result = get_vision_llm_for_image_summarization()

    assert result is None
    reset_default.assert_called_once()
    invalidate_cache.assert_called_once()


def test_paid_blocked_but_default_not_yahont_does_not_invalidate() -> None:
    """`reset_default_vision_if_yahont` returning False means nothing was
    written — nothing to invalidate."""
    with ExitStack() as stack:
        _enter_managed_env(stack, is_trial=False)
        stack.enter_context(
            patch(f"{_PATCH_PREFIX}.get_credit_wallet", return_value=None)
        )
        stack.enter_context(
            patch(
                f"{_PATCH_PREFIX}.reset_default_vision_if_yahont",
                return_value=False,
            )
        )
        invalidate_cache = stack.enter_context(
            patch(f"{_PATCH_PREFIX}.invalidate_provider_listing_cache")
        )

        result = get_vision_llm_for_image_summarization()

    assert result is None
    invalidate_cache.assert_not_called()


def test_paid_wallet_read_error_blocks_without_resetting_default() -> None:
    with ExitStack() as stack:
        _enter_managed_env(stack, is_trial=False)
        stack.enter_context(
            patch(
                f"{_PATCH_PREFIX}.get_credit_wallet",
                side_effect=RuntimeError("db down"),
            )
        )
        reset_default = stack.enter_context(
            patch(f"{_PATCH_PREFIX}.reset_default_vision_if_yahont")
        )

        result = get_vision_llm_for_image_summarization()

    assert result is None
    reset_default.assert_not_called()
