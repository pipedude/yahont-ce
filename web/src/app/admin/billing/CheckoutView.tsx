"use client";

import { useState, useMemo, useEffect } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Section } from "@/layouts/general-layouts";
import { InputHorizontal } from "@opal/layouts";
import { Button, Divider, InputCheckbox } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import Card from "@/refresh-components/cards/Card";
import { SvgUsers } from "@opal/icons";
import { BillingApiError, createCheckoutSession } from "@/lib/billing/svc";
import { useOccupiedSeats } from "@/hooks/useOccupiedSeats";
import { BUSINESS_PLAN_CODE, BILLING_PERIOD } from "@/lib/billing/plan-catalog";
import type { PlanCatalog } from "@/lib/billing/plan-catalog";
import { formatCpAmount } from "@/lib/billing/format-money";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import useSWR from "swr";
import { useUser } from "@/providers/UserProvider";
import { formatDateShort } from "@/lib/dateUtils";
import { rememberPendingCharge } from "@/lib/billing/pending-charge";
import type { PlanType } from "@/lib/billing/types";
import { InputNumber } from "@opal/components";
import useUsers from "@/hooks/useUsers";
import BillingOption from "./BillingOption";

// ----------------------------------------------------------------------------
// CheckoutView
// ----------------------------------------------------------------------------

interface CheckoutViewProps {
  onAdjustPlan: () => void;
}

export default function CheckoutView({ onAdjustPlan }: CheckoutViewProps) {
  const t = useTranslations("admin.billing");
  const locale = useLocale();
  const { user } = useUser();
  const { data: usersData } = useUsers({ includeApiKeys: false });

  // §4.9: the occupancy formula must MATCH the server's — the unified
  // backend predicate, not a local usedSeats + pendingSeats computation.
  const { data: occupiedSeatsData, refresh: mutateOccupancy } =
    useOccupiedSeats();
  const acceptedUsers =
    usersData?.accepted?.filter((u) => u.is_active).length ?? 0;
  const slackUsers =
    usersData?.slack_users?.filter((u) => u.is_active).length ?? 0;
  const minRequiredSeats = Math.max(
    1,
    occupiedSeatsData?.occupied_seats ?? acceptedUsers + slackUsers
  );

  const [seats, setSeats] = useState(minRequiredSeats);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // ЮKassa requires the payer's consent on recurring charges before the
  // auto-payment is set up — the fact is recorded by the control plane.
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Update seats if minRequiredSeats changes (e.g., after user data loads)
  useEffect(() => {
    if (seats < minRequiredSeats) {
      setSeats(minRequiredSeats);
    }
  }, [minRequiredSeats, seats]);

  const { data: catalog } = useSWR<PlanCatalog>(
    SWR_KEYS.billingPlans,
    errorHandlingFetcher
  );
  const businessPlan = catalog?.plans.find(
    (plan) => plan.code === BUSINESS_PLAN_CODE
  );
  const monthlyPrice = businessPlan
    ? formatCpAmount(businessPlan.price_monthly)
    : "";
  // The solo tariff (one person, no multi-seat pricing) — informational on
  // this page; the checkout always bills the multi-seat price.
  const soloMonthlyPrice = businessPlan
    ? formatCpAmount(businessPlan.solo_price_monthly)
    : "";

  // The next charge is one calendar month AFTER the payment, clamped to
  // the target month's last day — the control plane anchors the paid period with
  // `add_months` (Jan 31 + 1 month = Feb 28), so the shown date must not
  // roll over into March.
  const nextChargeDate = useMemo(() => {
    const now = new Date();
    const target = new Date(now.getFullYear(), now.getMonth() + 1, 1);
    const lastDayOfTargetMonth = new Date(
      target.getFullYear(),
      target.getMonth() + 1,
      0
    ).getDate();
    target.setDate(Math.min(now.getDate(), lastDayOfTargetMonth));
    return formatDateShort(target.toISOString(), locale);
  }, [locale]);

  const handleSubmit = async () => {
    setIsSubmitting(true);
    setError(null);

    try {
      const response = await createCheckoutSession({
        billing_period: BILLING_PERIOD,
        seats,
        email: user?.email,
        // The return must land on THIS origin — the session cookie is
        // host-bound (the same contract as payInvoice / card binding).
        return_url: `${window.location.origin}/admin/billing?yk_return=1`,
      });

      if (response.checkout_url) {
        // The return polls this charge's status: the id cannot ride the
        // return_url — the control plane creates the charge during THIS
        // request.
        rememberPendingCharge(response.charge_id);
        window.location.href = response.checkout_url;
      } else {
        throw new Error("Invalid response from checkout session");
      }
    } catch (err) {
      console.error("Error creating checkout session:", err);
      setError(
        err instanceof Error
          ? err.message
          : t("checkout.createSessionFailed.error")
      );
      // 409 seats_below_occupancy: the count went stale between the render
      // and the request — re-read the occupancy so the floor is current
      // (the control plane never accepts fewer seats than occupied).
      if (err instanceof BillingApiError && err.status === 409) {
        await mutateOccupancy();
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Card padding={0} gap={0} alignItems="stretch">
      {/* Header. Plain Tailwind `sm:` (724px matches Opal's own SMALL_BREAKPOINT_PX,
          tailwind-themes/tailwind.config.js) instead of a JS isMobile check —
          the app-wide idiom for simple row reflow (PerUserUsagePanel's
          grid-cols-2 sm:grid-cols-4, InputHorizontal's own responsive CSS). */}
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
          <Text headingH2 text04>
            {t("checkout.plan.title")}
          </Text>
        </Section>
        <Button prominence="secondary" onClick={onAdjustPlan}>
          {t("checkout.adjustPlan.label")}
        </Button>
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
          {/* The annual period is not sold at launch — the API
              rejects it. Two INFORMATIONAL cards show what the tariff
              contains: a solo seat (one person) and the multi-seat price
              the checkout actually bills. */}
          <InputHorizontal
            title={t("checkout.billingCycle.title")}
            description={t("checkout.billingCycle.description")}
            withLabel
            responsive
          >
            <Section
              className="flex-col w-auto sm:flex-row sm:w-fit"
              gap={2}
              height="auto"
              justifyContent="start"
            >
              <BillingOption
                tone="green"
                title={t("checkout.soloSeat.label")}
                price={soloMonthlyPrice}
              />
              <BillingOption
                tone="blue"
                title={t("checkout.multiSeats.label")}
                price={monthlyPrice}
              />
            </Section>
          </InputHorizontal>

          <Divider paddingParallel={0} paddingPerpendicular={0} />

          {/* Seats */}
          <InputHorizontal
            title={t("checkout.seats.title")}
            description={t("checkout.seats.description", {
              count: minRequiredSeats,
            })}
            withLabel
            responsive
          >
            <InputNumber
              value={seats}
              onChange={(v) => setSeats(v ?? minRequiredSeats)}
              min={minRequiredSeats}
              defaultValue={minRequiredSeats}
              showReset
            />
          </InputHorizontal>
        </Section>
      </div>

      {/* Footer */}
      <Section
        className="flex-col items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-0"
        padding={4}
        height="auto"
      >
        {error ? (
          <Text secondaryBody className="billing-error-text">
            {error}
          </Text>
        ) : (
          <Text secondaryBody text03>
            {t.rich("checkout.nextCharge.text", {
              date: nextChargeDate,
              value: (chunks) => (
                <Text secondaryBody text04>
                  {chunks}
                </Text>
              ),
            })}
          </Text>
        )}
        <div className="flex items-center gap-2">
          <InputCheckbox checked={consent} onCheckedChange={setConsent} />
          <Text secondaryBody text03>
            {t("checkout.consent.label")}
          </Text>
        </div>
        <div className="w-full sm:w-auto">
          <Button
            disabled={isSubmitting || !consent}
            onClick={handleSubmit}
            width="full"
          >
            {isSubmitting
              ? t("checkout.loading.label")
              : t("checkout.continueToPayment.label")}
          </Button>
        </div>
      </Section>
    </Card>
  );
}
