"use client";

/**
 * The Manage Plan overview: the state banners, the subscription card and
 * the sections. The three seat numbers (paid / occupied / from
 * invitations) are always visible — «оплатил 5, работают 3, а места нет»
 * must read as an unaccepted invitation, not as a bug.
 */

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import useSWR from "swr";
import { Section } from "@/layouts/general-layouts";
import { Button, Text } from "@opal/components";
import { SvgArrowRight } from "@opal/icons";
import { MessageCard } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import Card from "@/refresh-components/cards/Card";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useBillingInformation } from "@/hooks/useBillingInformation";
import { useOccupiedSeats } from "@/hooks/useOccupiedSeats";
import useUsers from "@/hooks/useUsers";
import { BillingStatus, InvoiceListResponse } from "@/lib/billing/types";
import { PlanCatalog, BUSINESS_PLAN_CODE } from "@/lib/billing/plan-catalog";
import { formatCpAmount } from "@/lib/billing/format-money";
import { formatDateShort } from "@/lib/dateUtils";
import {
  payInvoice,
  reactivateSubscription,
  resumeSubscription,
  updatePlan,
} from "@/lib/billing/svc";
import { useDeclineMessage } from "@/lib/billing/cancellation-reasons";
import { rememberPendingCharge } from "@/lib/billing/pending-charge";
import { toast } from "@opal/layouts";

import PaymentMethodsSection, {
  invalidateBillingTree,
} from "./PaymentMethodsSection";
import BillingAccountSection from "./BillingAccountSection";
import InvoiceHistorySection from "./InvoiceHistorySection";
import RefundRequestsSection from "./RefundRequestsSection";
import CancelSubscriptionModal from "./CancelSubscriptionModal";

export default function ManagePlanOverview() {
  const t = useTranslations("admin.billing.manage");
  const locale = useLocale();
  const { data: billing } = useBillingInformation();
  const { data: occupiedSeatsData } = useOccupiedSeats();
  // The third number: «оплатил 5, работают 3, а места нет»
  // must read as an unaccepted invitation, not as a bug.
  const { data: usersData } = useUsers({ includeApiKeys: false });

  const [cancelOpen, setCancelOpen] = useState(false);
  const [reactivating, setReactivating] = useState(false);
  const [payingInvoice, setPayingInvoice] = useState(false);

  const { data: catalog } = useSWR<PlanCatalog>(
    SWR_KEYS.billingPlans,
    errorHandlingFetcher
  );
  // The decline reason for the past_due/unpaid banner: the last failed
  // attempt of the OPEN invoice (the same fetch the history makes).
  // The union is narrowed manually: the hooks must run before the guard.
  const snapshotStatus = billing && "status" in billing ? billing.status : null;
  const pastDue =
    snapshotStatus === BillingStatus.PAST_DUE ||
    snapshotStatus === BillingStatus.UNPAID;
  const { data: openInvoices } = useSWR<InvoiceListResponse>(
    pastDue ? SWR_KEYS.billingInvoices : null,
    errorHandlingFetcher
  );
  const declineMessage = useDeclineMessage();

  if (
    !billing ||
    !("status" in billing) ||
    billing.status === null ||
    billing.seats === null
  ) {
    return null;
  }

  // A trial converts through the checkout: `/plan/update` refuses it by
  // design (409 trial_conversion_required) and the trial expires without a
  // charge, so neither action below has anything to do (visible but
  // disabled, with the reason in the tooltip).
  const isTrialing = billing.status === BillingStatus.TRIALING;
  // For a canceled subscription the only live action is the checkout
  // restart (the banner above) — seats/cancel would 409.
  const isCanceled = billing.status === BillingStatus.CANCELED;
  // `unpaid` is gated the same way: the only meaningful action is paying
  // (the banner's reactivate). A seat increase would 402 anyway; a cancel
  // would write a flag nothing consumes (the renewal exits before the
  // cancel guard for non-active statuses) — the control plane rejects both
  // at 409.
  const isUnpaid = billing.status === BillingStatus.UNPAID;
  // `past_due` blocks only the seats wizard: an increase is a guaranteed
  // 402 (the control plane raises `subscription_not_active` for any
  // non-active status), and the decrease is niche — the banner's Pay now is
  // the action the page pushes. Cancel stays live: the flag is consumable on
  // `past_due` by design (a dunning recovery honors it).
  const isPastDue = billing.status === BillingStatus.PAST_DUE;
  // Cancel-pending is `active` + a flag: an increase would charge for
  // seats that die at the boundary, a decrease is discarded by the
  // cancel — so seats close, and a second Cancel has nothing to do
  // (undo lives in the banner's Resume).
  const isCancelPending = billing.cancel_at_period_end;

  const paid = billing.seats;
  const occupied = occupiedSeatsData?.occupied_seats ?? 0;
  const invitations = usersData?.invited?.length ?? 0;
  const planned = billing.pending_quantity_decrease;

  const businessPlan = catalog?.plans.find(
    (plan) => plan.code === BUSINESS_PLAN_CODE
  );
  const pricePerSeat = businessPlan
    ? formatCpAmount(businessPlan.price_monthly)
    : "";

  const openWizard = () => {
    window.location.href = "/admin/billing/manage?wizard=seats";
  };

  const openInvoice = openInvoices?.invoices.find(
    (invoice) => invoice.status === "open"
  );
  const lastDecline = (openInvoice?.charges ?? [])
    .filter((charge) => charge.status === "canceled")
    .at(-1);
  const declineReason = declineMessage(lastDecline?.cancellation_reason);

  const handleResume = async () => {
    try {
      await resumeSubscription();
      await invalidateBillingTree();
      toast.success(t("toasts.resumed"));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("toasts.resumed"));
    }
  };

  const handlePayOpenInvoice = async () => {
    if (!openInvoice) {
      return;
    }
    setPayingInvoice(true);
    try {
      const result = await payInvoice(
        openInvoice.id,
        `${window.location.origin}/admin/billing/manage?yk_return=1`
      );
      // The return polls this charge — the id is created during this
      // request, so it travels through sessionStorage.
      rememberPendingCharge(result.charge_id);
      window.location.href = result.confirmation_url;
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("banners.payNow"));
      setPayingInvoice(false);
    }
  };

  const handleReactivate = async () => {
    setReactivating(true);
    try {
      const { confirmation_url, charge_id } = await reactivateSubscription(
        `${window.location.origin}/admin/billing/manage?yk_return=1`
      );
      if (!confirmation_url) {
        throw new Error(t("toasts.reactivateFailed"));
      }
      rememberPendingCharge(charge_id);
      window.location.href = confirmation_url;
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("toasts.reactivateFailed")
      );
      setReactivating(false);
    }
  };

  const handleCancelDecrease = async () => {
    // Re-planning to the CURRENT quantity clears the pending decrease (the
    // control plane overwrites and nulls it in one update).
    try {
      await updatePlan({
        quantity: paid,
        plan_code: "business",
        period: "monthly",
      });
      await invalidateBillingTree();
      toast.success(t("toasts.decreaseCanceled"));
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : t("pendingChange.cancelDecrease")
      );
    }
  };

  return (
    <div className="flex flex-col gap-6">
      {/* ── the state banners ─────────────────────────────── */}
      {isTrialing && billing.trial_end && (
        <MessageCard
          variant="info"
          title={t("banners.trialEnds", {
            date: formatDateShort(billing.trial_end, locale),
          })}
          // Both card actions below are disabled on a trial, so the banner
          // carries the one thing a trial admin can actually do: convert.
          rightChildren={
            // The same button the subscription card carries: primary with
            // the arrow. It lands on the checkout, not the overview —
            // `?upgrade=1` is the door into that view.
            <Button
              rightIcon={SvgArrowRight}
              onClick={() => {
                window.location.href = "/admin/billing?upgrade=1";
              }}
            >
              {t("banners.upgrade")}
            </Button>
          }
        />
      )}
      {billing.status === BillingStatus.PAST_DUE && (
        <MessageCard
          variant="error"
          title={t("banners.pastDue", {
            reason: declineReason,
            date: billing.grace_ends_at
              ? formatDateShort(billing.grace_ends_at, locale)
              : "",
          })}
          // The banner carries the debt's own action — paying
          // the OPEN renewal invoice (the period-preserving path). No
          // "update card" here: Payment Methods below already binds one,
          // and the next dunning beat retries off-session.
          rightChildren={
            openInvoice ? (
              <Button
                rightIcon={SvgArrowRight}
                disabled={payingInvoice}
                onClick={handlePayOpenInvoice}
              >
                {t("banners.payNow")}
              </Button>
            ) : undefined
          }
        />
      )}
      {billing.status === BillingStatus.UNPAID && (
        <MessageCard
          variant="error"
          title={t("banners.unpaid")}
          // The unpaid banner's CTA splits by `seats`.
          // seats > 0 — an ex-paid subscription: `reactivate` pays a new
          // full period from the payment date (the open invoice in the
          // history is the period-preserving alternative). seats == 0 —
          // an expired trial: there is no debt, so the conversion goes
          // through the seat-picking checkout, same as the trial/canceled
          // upgrade views.
          rightChildren={
            <Button
              rightIcon={SvgArrowRight}
              disabled={reactivating}
              onClick={
                billing.seats === 0
                  ? () => {
                      window.location.href = "/admin/billing?upgrade=1";
                    }
                  : handleReactivate
              }
            >
              {billing.seats === 0
                ? t("banners.upgrade")
                : t("banners.payAndRestore")}
            </Button>
          }
        />
      )}
      {billing.status === BillingStatus.CANCELED && (
        <MessageCard
          variant="error"
          title={t("banners.canceled")}
          // The canceled subscription's self-serve return is an
          // explicit paid checkout — the same view the trial conversion
          // uses. `reactivate` is for `unpaid` only.
          rightChildren={
            <Button
              rightIcon={SvgArrowRight}
              onClick={() => {
                window.location.href = "/admin/billing?upgrade=1";
              }}
            >
              {t("banners.resubscribe")}
            </Button>
          }
        />
      )}
      {billing.cancel_at_period_end &&
        billing.status !== BillingStatus.CANCELED && (
          <MessageCard
            variant="warning"
            title={t("banners.cancelPending", {
              date: formatDateShort(billing.current_period_end, locale),
            })}
            // The resume lives IN the banner: the cancellation is
            // reversible until the period end without data loss.
            rightChildren={
              <Button prominence="secondary" onClick={handleResume}>
                {t("banners.resume")}
              </Button>
            }
          />
        )}
      {billing.pending_quantity_decrease != null && (
        <MessageCard
          variant="warning"
          title={t("pendingChange.title", {
            date: formatDateShort(billing.current_period_end, locale),
          })}
          description={
            occupied > (billing.pending_quantity_decrease ?? 0)
              ? t("pendingChange.cutoffWarning", {
                  planned: billing.pending_quantity_decrease,
                  occupied,
                })
              : t("pendingChange.description", {
                  planned: billing.pending_quantity_decrease,
                  date: formatDateShort(billing.current_period_end, locale),
                })
          }
          // The banner's own action: a defined but never-rendered handler
          // is a defect (the resume banner got the same treatment). Clearing
          // goes through the same path the wizard uses: re-plan to the PAID
          // quantity.
          rightChildren={
            <Button prominence="secondary" onClick={handleCancelDecrease}>
              {t("pendingChange.cancelDecrease")}
            </Button>
          }
        />
      )}

      {/* ── the subscription card ───────────────────────────────────── */}
      <ContentAction
        title={t("currentSubscription.label")}
        sizePreset="main-content"
        variant="section"
        padding={0}
      />
      <Card>
        <ContentAction
          title={t("subscription.title")}
          description={t("subscription.pricePerSeat", { price: pricePerSeat })}
          sizePreset="main-ui"
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
              <Button
                prominence="primary"
                onClick={openWizard}
                disabled={
                  isTrialing ||
                  isCanceled ||
                  isUnpaid ||
                  isPastDue ||
                  isCancelPending
                }
                tooltip={
                  isTrialing
                    ? t("subscription.changeSeatsTrialHint")
                    : isPastDue
                      ? t("subscription.changeSeatsPastDueHint")
                      : isCancelPending
                        ? t("subscription.changeSeatsCancelPendingHint")
                        : undefined
                }
              >
                {t("subscription.changeSeats")}
              </Button>
              <Button
                prominence="secondary"
                variant="danger"
                onClick={() => setCancelOpen(true)}
                disabled={
                  isTrialing || isCanceled || isUnpaid || isCancelPending
                }
                tooltip={
                  isTrialing
                    ? t("subscription.cancelTrialHint")
                    : isCancelPending
                      ? t("subscription.cancelPendingHint")
                      : undefined
                }
              >
                {t("subscription.cancel")}
              </Button>
            </Section>
          }
        />
        <Section
          flexDirection="column"
          alignItems="start"
          gap={1}
          height="auto"
        >
          <Text font="secondary-body" color="text-03">
            {t("subscription.seatsLine", {
              paid,
              occupied,
              invitations,
            })}
          </Text>
          {!isCanceled && (
            <Text font="secondary-body" color="text-03">
              {t("subscription.nextCharge", {
                date: formatDateShort(billing.current_period_end, locale),
              })}
            </Text>
          )}
        </Section>
      </Card>

      <PaymentMethodsSection />
      <BillingAccountSection />
      <InvoiceHistorySection />
      <RefundRequestsSection />

      {cancelOpen && (
        <CancelSubscriptionModal
          accessUntil={billing.current_period_end}
          onClose={() => setCancelOpen(false)}
        />
      )}
    </div>
  );
}
