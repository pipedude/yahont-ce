"use client";

/**
 * The LLM-packages card: a simple linear purchase — no proration, no
 * wizard. Rendered in the same Card style as the plan and seats cards on
 * this page (title + description on the left, the controls on the right).
 * The button is disabled by the SNAPSHOT states with their own hints:
 * trialing, dunning, a requested cancel. The crediting happens ONLY by the
 * webhook: no optimistic balance update — the waiting state instead.
 * `save_payment_method=false`: the subscription's default method is not
 * overwritten.
 */

import { useState } from "react";
import { useTranslations } from "next-intl";
import useSWR, { mutate } from "swr";
import { Section } from "@/layouts/general-layouts";
import { Button } from "@opal/components";
import { ContentAction, toast } from "@opal/layouts";
import { markdown } from "@opal/utils";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
import { InputNumber } from "@opal/components";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useBillingInformation } from "@/hooks/useBillingInformation";
import { SWR_KEYS } from "@/lib/swr-keys";
import { invalidateBillingInformation } from "@/lib/billing/information-keys";
import { BillingStatus } from "@/lib/billing/types";
import { parseAmountToKop, formatMoneyWhole } from "@/lib/billing/format-money";
import { purchaseLlmCredits } from "@/lib/billing/svc";
import { PlanCatalog } from "@/lib/billing/plan-catalog";
import { rememberPendingCharge } from "@/lib/billing/pending-charge";

export default function LlmPackagesCard() {
  const t = useTranslations("admin.billing.manage");
  const { data: billing } = useBillingInformation();
  const { data: catalog } = useSWR<PlanCatalog>(
    SWR_KEYS.billingPlans,
    errorHandlingFetcher
  );

  const [count, setCount] = useState(1);
  const [busy, setBusy] = useState(false);
  const [crediting, setCrediting] = useState(false);

  const pkg = catalog?.llm_package;
  const maxPerCharge = pkg?.max_per_charge ?? 10;

  // The button is disabled by the SNAPSHOT states with their own hints —
  // the UI must not wait for the 402 to explain itself.
  const snapshotStatus = billing && "status" in billing ? billing.status : null;
  const isTrial = snapshotStatus === BillingStatus.TRIALING;
  // `unpaid` joins past_due here: the control plane refuses a purchase on a
  // non-active subscription (402 subscription_not_active) — the UI must
  // not wait for it.
  const isDelinquent =
    snapshotStatus === BillingStatus.PAST_DUE ||
    snapshotStatus === BillingStatus.UNPAID;
  const isCancelPending =
    billing && "cancel_at_period_end" in billing
      ? billing.cancel_at_period_end
      : false;
  // `canceled` is guarded EXPLICITLY — it happens to imply
  // `cancel_at_period_end` today (the flag survives the cancel as an
  // audit trail), but that is a side effect, not the intent.
  const isCanceled = snapshotStatus === BillingStatus.CANCELED;
  const hint = isTrial
    ? t("llm.trialHint")
    : isDelinquent
      ? t("llm.dunningHint")
      : isCanceled
        ? t("llm.canceled")
        : isCancelPending
          ? t("llm.cancelPending")
          : null;
  // The guards disable the button — the hint alone would leave
  // the admin clicking into a raw 402.
  const disabled =
    isTrial || isDelinquent || isCanceled || isCancelPending || busy;

  const totalKop = pkg ? count * parseAmountToKop(pkg.price) : 0;

  const handleBuy = async () => {
    if (!pkg) {
      return;
    }
    setBusy(true);
    try {
      const result = await purchaseLlmCredits({
        package_count: count,
        return_url: `${window.location.origin}/admin/billing?yk_return=1`,
      });
      if (result.requires_payment && result.confirmation_url) {
        // The return polls this charge — the id is created during this
        // request, so it travels through sessionStorage.
        rememberPendingCharge(result.charge_id);
        window.location.href = result.confirmation_url;
        return;
      }
      // No optimistic balance update — the grant applies by the
      // webhook; the waiting state is honest (and stays on screen, not
      // only in a toast).
      setCrediting(true);
      toast.success(t("llm.crediting"));
      await Promise.all([
        invalidateBillingInformation(),
        mutate(SWR_KEYS.settings),
      ]);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("llm.buy", { amount: "" })
      );
    } finally {
      setBusy(false);
    }
  };

  if (!catalog || !pkg) {
    return null;
  }

  return (
    <Card>
      <ContentAction
        title={t("llm.title")}
        // The description prop takes text/markdown only — a component cannot
        // live inside it (that is why the "Usage page" pointer is a markdown
        // link and carries no icon). The route comes from code, not from the
        // translated string.
        description={markdown(
          t("llm.description", { usageUrl: ADMIN_ROUTES.USAGE.path })
        )}
        sizePreset="main-content"
        variant="section"
        padding={0}
        responsive
        rightChildren={
          // `width="full"` + `justifyContent="end"`: the responsive
          // ContentAction grid gives the right slot a 12rem minimum, so a
          // shrink-wrapped child would hug the slot's LEFT edge.
          <Section
            flexDirection="row"
            gap={2}
            alignItems="center"
            justifyContent="end"
            height="auto"
            width="full"
          >
            <Section
              flexDirection="row"
              gap={1}
              alignItems="center"
              height="auto"
              width="auto"
            >
              <Text secondaryBody text03>
                {t("llm.quantity")}
              </Text>
              <div className="w-24">
                <InputNumber
                  value={count}
                  onChange={(v) => setCount(v ?? 1)}
                  min={1}
                  max={maxPerCharge}
                />
              </div>
            </Section>
            <Button
              prominence="primary"
              onClick={handleBuy}
              disabled={disabled}
              tooltip={hint ?? undefined}
            >
              {t("llm.buy", { amount: formatMoneyWhole(totalKop) })}
            </Button>
          </Section>
        }
      />
      {/* The waiting state stays on screen after a non-redirect
          purchase. The guard reasons (trial/dunning/cancel-pending) live
          in the button tooltip — the card itself stays clean. */}
      {crediting && (
        <Text secondaryBody text05>
          {t("llm.crediting")}
        </Text>
      )}
    </Card>
  );
}
