"use client";

/**
 * The seat-change wizard shell. Step 1 — the quantity (NO occupancy
 * floor: planning below occupancy is allowed, the control plane applies
 * max(plan, occupied) at the boundary). Step 2 — the preview for an
 * increase (the proration, the consent, the payment) or the schedule
 * screen for a decrease (no money, no consent).
 *
 * The layout mirrors the checkout card (the same header, content area and
 * footer): the two screens describe the same tariff, so they share one
 * visual language. The MONEY stays different on purpose — the
 * checkout sells a new period, this wizard prorates the current one.
 */

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button, Divider, MessageCard, Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { InputHorizontal } from "@opal/layouts";
import Card from "@/refresh-components/cards/Card";
import { InputNumber } from "@opal/components";
import { SvgArrowRight, SvgUsers } from "@opal/icons";
import { useBillingInformation } from "@/hooks/useBillingInformation";
import { useOccupiedSeats } from "@/hooks/useOccupiedSeats";
import {
  billableAmountKop,
  BUSINESS_PLAN_CODE,
  BILLING_PERIOD,
} from "@/lib/billing/plan-catalog";
import { BillingStatus } from "@/lib/billing/types";
import { previewPlanChange } from "@/lib/billing/svc";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import useSWR from "swr";
import type { PlanCatalog } from "@/lib/billing/plan-catalog";
import {
  formatCpAmount,
  formatMoney,
  parseAmountToKop,
} from "@/lib/billing/format-money";
import type { ProrationPreview } from "@/lib/billing/types";
import { formatDateShort } from "@/lib/dateUtils";
import BillingOption from "../BillingOption";
import PlanChangeStep2 from "./PlanChangeStep2";

/** The product floor: a paid subscription always carries at least one seat. */
const MIN_SEATS = 1;

export default function PlanChangeWizard({
  step,
  onStepChange,
  onDone,
}: {
  /** Owned by the page: its Back returns to step 1 while on step 2. */
  step: 1 | 2;
  onStepChange: (step: 1 | 2) => void;
  onDone: () => void;
}) {
  const t = useTranslations("admin.billing.manage.wizard");
  const locale = useLocale();
  // The tariff cards are shared with the checkout — one wording, one look.
  const tCheckout = useTranslations("admin.billing.checkout");
  const tBilling = useTranslations("admin.billing");
  const { data: billing } = useBillingInformation();
  const { data: occupiedData } = useOccupiedSeats();
  // The price source is the catalog — no hardcode.
  const { data: catalog } = useSWR<PlanCatalog>(
    SWR_KEYS.billingPlans,
    errorHandlingFetcher
  );
  const businessPlan = catalog?.plans.find(
    (plan) => plan.code === BUSINESS_PLAN_CODE
  );

  const [quantity, setQuantity] = useState<number | null>(null);
  const [preview, setPreview] = useState<ProrationPreview | null>(null);

  const paid = billing && "seats" in billing ? (billing.seats ?? 0) : 0;
  const pendingDecrease =
    billing && "pending_quantity_decrease" in billing
      ? billing.pending_quantity_decrease
      : null;
  const occupiedCount = occupiedData?.occupied_seats ?? 0;
  // The floor is 1, not the occupancy: planning below occupancy is allowed
  // at this step (the control plane applies max(plan, occupied) at the
  // boundary). A trial has `seats = 0`, and showing 0 let the stepper
  // increment it — hence the explicit floor.
  const current = quantity ?? Math.max(MIN_SEATS, paid);
  // Same-quantity submit has exactly ONE meaning: it clears a planned
  // decrease. Without one it is a no-op that used to sail through step 2
  // as a "decrease" screen and toast «Paid» — the control plane answers
  // `applied: true, scheduled: false` (no `charged`), which the toast
  // branch misread as a payment (3→3).
  const isNoChange = current === paid;
  const nextDisabled = isNoChange && pendingDecrease == null;

  const goPreview = async () => {
    const response = await previewPlanChange({
      quantity: current,
      plan_code: BUSINESS_PLAN_CODE,
      period: BILLING_PERIOD,
    });
    setPreview(response);
    onStepChange(2);
  };

  // A trial converts through the checkout: the control plane refuses `/plan/update`
  // with 409 `trial_conversion_required`, so the wizard would dead-end at
  // the payment step. The card's button is disabled on a trial, but the
  // deep link (`?wizard=seats`) still lands here — hence the guard.
  const isTrialing =
    billing !== undefined &&
    "status" in billing &&
    billing.status === BillingStatus.TRIALING;
  // Seat mutations are active-only end to end: the control plane guards the
  // increase (402 `subscription_not_active`) but lets a decrease be PLANNED
  // on `past_due`/`unpaid` — a write the disabled button means to forbid
  // and the `?wizard=seats` deep link would otherwise reach.
  // `active` + cancel_at_period_end joins: an increase charges for seats
  // that die at the boundary, a decrease is discarded by the cancel.
  const cancelPending =
    billing !== undefined &&
    "cancel_at_period_end" in billing &&
    billing.cancel_at_period_end === true;
  const seatsBlocked =
    billing !== undefined &&
    "status" in billing &&
    ((billing.status !== BillingStatus.ACTIVE && !isTrialing) || cancelPending);

  if (isTrialing) {
    return (
      <Card padding={0} gap={0} alignItems="stretch">
        <Section
          className="flex-col items-start gap-3 sm:flex-row sm:justify-between sm:gap-0"
          padding={4}
          height="auto"
        >
          <Section
            flexDirection="column"
            alignItems="start"
            gap={1}
            height="auto"
            width="fit"
          >
            <SvgUsers size={24} />
            <Text font="heading-h2" color="text-04">
              {t("step1Title")}
            </Text>
          </Section>
        </Section>
        <div className="billing-content-area">
          <Section
            flexDirection="column"
            alignItems="stretch"
            gap={4}
            padding={4}
            height="auto"
          >
            <MessageCard
              variant="info"
              title={t("trialBlocked.title")}
              description={t("trialBlocked.description")}
              rightChildren={
                <Button
                  rightIcon={SvgArrowRight}
                  onClick={() => {
                    window.location.href = "/admin/billing?upgrade=1";
                  }}
                >
                  {tBilling("subscription.upgradeNow.label")}
                </Button>
              }
            />
          </Section>
        </div>
      </Card>
    );
  }

  if (seatsBlocked) {
    return (
      <Card padding={0} gap={0} alignItems="stretch">
        <Section
          className="flex-col items-start gap-3 sm:flex-row sm:justify-between sm:gap-0"
          padding={4}
          height="auto"
        >
          <Section
            flexDirection="column"
            alignItems="start"
            gap={1}
            height="auto"
            width="fit"
          >
            <SvgUsers size={24} />
            <Text font="heading-h2" color="text-04">
              {t("step1Title")}
            </Text>
          </Section>
        </Section>
        <div className="billing-content-area">
          <Section
            flexDirection="column"
            alignItems="stretch"
            gap={4}
            padding={4}
            height="auto"
          >
            <MessageCard
              variant="info"
              title={
                cancelPending ? t("blockedCancel.title") : t("blocked.title")
              }
              description={
                cancelPending
                  ? t("blockedCancel.description")
                  : t("blocked.description")
              }
              rightChildren={
                <Button rightIcon={SvgArrowRight} onClick={onDone}>
                  {t("blocked.cta")}
                </Button>
              }
            />
          </Section>
        </div>
      </Card>
    );
  }

  if (step === 2) {
    return (
      <PlanChangeStep2
        preview={preview}
        quantity={current}
        was={paid}
        pendingDecrease={pendingDecrease}
        plan={businessPlan ?? null}
        anchorDate={
          billing && "current_period_end" in billing
            ? billing.current_period_end
            : null
        }
        onDone={onDone}
      />
    );
  }

  return (
    <Card padding={0} gap={0} alignItems="stretch">
      {/* Header — the same shape as the checkout card header: icon + title
          on the left, the secondary action on the right. */}
      <Section
        className="flex-col items-start gap-3 sm:flex-row sm:justify-between sm:gap-0"
        padding={4}
        height="auto"
      >
        <Section
          flexDirection="column"
          alignItems="start"
          gap={1}
          height="auto"
          width="fit"
        >
          <SvgUsers size={24} />
          <Text font="heading-h2" color="text-04">
            {t("step1Title")}
          </Text>
        </Section>
      </Section>

      {/* Content */}
      <div className="billing-content-area">
        <Section
          flexDirection="column"
          alignItems="stretch"
          gap={4}
          padding={4}
          height="auto"
        >
          {/* The same informational cards the checkout shows: what the
              tariff contains (a solo seat) and what a seat costs. */}
          {/* The description carries what the subscription ACTUALLY bills
              now (the control plane's non-linear rule, mirrored for display): the
              per-seat price already lives in the cards beside it. */}
          <InputHorizontal
            title={t("planCard")}
            description={
              businessPlan
                ? paid >= MIN_SEATS
                  ? t("currentCharge", {
                      amount: formatMoney(
                        billableAmountKop(paid, businessPlan)
                      ),
                    })
                  : t("trialNoCharge")
                : undefined
            }
            withLabel
            responsive
          >
            <Section
              className="flex-col w-auto sm:flex-row sm:w-fit"
              gap={2}
              height="auto"
              justifyContent="start"
            >
              {businessPlan && (
                <>
                  <BillingOption
                    tone="green"
                    title={tCheckout("soloSeat.label")}
                    price={formatCpAmount(businessPlan.solo_price_monthly)}
                  />
                  <BillingOption
                    tone="blue"
                    title={tCheckout("multiSeats.label")}
                    price={formatCpAmount(businessPlan.price_monthly)}
                  />
                </>
              )}
            </Section>
          </InputHorizontal>

          <Divider paddingParallel={0} paddingPerpendicular={0} />

          {/* The same control the checkout uses (one visual language); the
              reset returns to the currently paid quantity. */}
          <InputHorizontal
            title={t("seatsTitle")}
            description={t("occupiedNow", { paid, occupied: occupiedCount })}
            withLabel
            responsive
          >
            <InputNumber
              value={current}
              onChange={(value) => setQuantity(value ?? MIN_SEATS)}
              min={MIN_SEATS}
              defaultValue={Math.max(MIN_SEATS, paid)}
              showReset
            />
          </InputHorizontal>

          {current < occupiedCount && (
            <Text font="secondary-body" color="text-03">
              {t("occupiedWarning", {
                occupied: occupiedCount,
                planned: current,
                date: formatDateShort(
                  billing && "current_period_end" in billing
                    ? billing.current_period_end
                    : null,
                  locale
                ),
              })}
            </Text>
          )}
        </Section>
      </div>

      {/* Footer — the checkout's footer shape: an informative line on the
          left, the primary action on the right. */}
      <Section
        className="flex-col items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-0"
        padding={4}
        height="auto"
      >
        <Text font="secondary-body" color="text-03">
          {t("footerHint")}
        </Text>
        <div className="w-full sm:w-auto">
          <Button
            prominence="primary"
            onClick={goPreview}
            width="full"
            disabled={nextDisabled}
            tooltip={nextDisabled ? t("noChangeHint") : undefined}
          >
            {t("next")}
          </Button>
        </div>
      </Section>
    </Card>
  );
}
