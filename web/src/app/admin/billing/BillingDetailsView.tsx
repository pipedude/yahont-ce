"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { markdown } from "@opal/utils";
import { Section } from "@/layouts/general-layouts";
import {
  ContentAction,
  InputErrorText,
  InputVertical,
  toast,
} from "@opal/layouts";
import Card from "@/refresh-components/cards/Card";
import { Button, MessageCard } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import InfoBlock from "@/refresh-components/messages/InfoBlock";
import {
  SvgUsers,
  SvgExternalLink,
  SvgArrowRight,
  SvgPlus,
  SvgWallet,
  SvgFileText,
  SvgOrganization,
} from "@opal/icons";
import {
  BillingInformation,
  BillingStatus,
  InvoiceListResponse,
  LicenseStatus,
} from "@/lib/billing/types";
import {
  updateSeatCount,
  claimLicense,
  payInvoice,
  reactivateSubscription,
  resumeSubscription,
} from "@/lib/billing/svc";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { rememberPendingCharge } from "@/lib/billing/pending-charge";
import { formatDateShort } from "@/lib/dateUtils";
import { humanReadableFormatShort } from "@opal/time";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { useSettings } from "@/lib/settings/hooks";
import { Tier } from "@/lib/settings/types";
import useUsers from "@/hooks/useUsers";
import { useOccupiedSeats } from "@/hooks/useOccupiedSeats";

// ----------------------------------------------------------------------------
// Constants
// ----------------------------------------------------------------------------

const GRACE_PERIOD_DAYS = 30;
const MS_PER_DAY = 86_400_000;

/** How many days of a trial are left. Rounds up so a partial day still counts
 *  as a whole day; the caller reads a non-positive result as "today". */
function trialDaysRemaining(trialEnd: Date, now: number = Date.now()): number {
  return Math.ceil((trialEnd.getTime() - now) / MS_PER_DAY);
}

// ----------------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------------

function getExpirationState(
  billing: BillingInformation,
  locale: string,
  license?: LicenseStatus
) {
  const isAnnualBilling = billing.billing_period === "annual";

  // Check license expiration for self-hosted
  if (license?.expires_at) {
    const expiresAt = new Date(license.expires_at);
    const now = new Date();
    const daysRemaining = Math.ceil(
      (expiresAt.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)
    );

    if (daysRemaining <= 0 || license.status === "expired") {
      const gracePeriodEnd = license.grace_period_end
        ? new Date(license.grace_period_end)
        : new Date(
            expiresAt.getTime() + GRACE_PERIOD_DAYS * 24 * 60 * 60 * 1000
          );
      const daysUntilDeletion = Math.max(
        0,
        Math.ceil(
          (gracePeriodEnd.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)
        )
      );
      return {
        variant: "error" as const,
        daysRemaining: 0,
        daysUntilDeletion,
        expirationDate: humanReadableFormatShort(gracePeriodEnd, locale),
      };
    }

    // Only show warning for annual subscriptions (30 days before expiration)
    if (isAnnualBilling && daysRemaining <= 30) {
      return {
        variant: "warning" as const,
        daysRemaining,
        expirationDate: humanReadableFormatShort(expiresAt, locale),
      };
    }
  }

  // Check billing expiration for cloud (only show warnings for canceled subscriptions)
  if (billing.cancel_at_period_end && billing.current_period_end) {
    const expiresAt = new Date(billing.current_period_end);
    const now = new Date();
    const daysRemaining = Math.ceil(
      (expiresAt.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)
    );

    if (daysRemaining <= 0) {
      const gracePeriodEnd = new Date(
        expiresAt.getTime() + GRACE_PERIOD_DAYS * 24 * 60 * 60 * 1000
      );
      const daysUntilDeletion = Math.max(
        0,
        Math.ceil(
          (gracePeriodEnd.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)
        )
      );
      return {
        variant: "error" as const,
        daysRemaining: 0,
        daysUntilDeletion,
        expirationDate: humanReadableFormatShort(gracePeriodEnd, locale),
      };
    }

    // Only show warning for annual subscriptions (30 days before expiration)
    // Monthly subscriptions auto-renew, so no warning needed
    if (isAnnualBilling && daysRemaining <= 30) {
      return {
        variant: "warning" as const,
        daysRemaining,
        expirationDate: humanReadableFormatShort(expiresAt, locale),
      };
    }
  }

  if (billing.status === "expired" || billing.status === "cancelled") {
    return {
      variant: "error" as const,
      daysRemaining: 0,
      daysUntilDeletion: GRACE_PERIOD_DAYS,
      expirationDate: "",
    };
  }

  return null;
}

// ----------------------------------------------------------------------------
// SubscriptionCard
// ----------------------------------------------------------------------------

function SubscriptionCard({
  billing,
  license,
  onViewPlans,
  onViewCheckout,
  isManualLicenseOnly,
  onRefresh,
}: {
  billing?: BillingInformation;
  license?: LicenseStatus;
  onViewPlans: () => void;
  onViewCheckout: () => void;
  isManualLicenseOnly?: boolean;
  onRefresh?: () => Promise<void>;
}) {
  const t = useTranslations("admin.billing");
  const locale = useLocale();
  const [isSyncing, setIsSyncing] = useState(false);

  const settings = useSettings();
  const tier = settings.tier;
  const isEnterprise = tier === Tier.ENTERPRISE || tier == null;
  const planName = isEnterprise
    ? t("subscription.enterprisePlan.name")
    : t("subscription.businessPlan.name");
  const PlanIcon = isEnterprise ? SvgOrganization : SvgUsers;
  const expirationDate = billing?.current_period_end ?? license?.expires_at;
  const formattedDate = formatDateShort(expirationDate, locale);

  const isExpiredFromBilling =
    billing?.status === "expired" ||
    billing?.status === "cancelled" ||
    billing?.status === BillingStatus.CANCELED;
  const isExpiredFromLicense =
    license?.status === "expired" ||
    license?.status === "gated_access" ||
    (license?.expires_at && new Date(license.expires_at) < new Date());
  const isExpired = isExpiredFromBilling || isExpiredFromLicense;
  const isCanceling = billing?.cancel_at_period_end;
  // The license is the entitlement, so a billing snapshot that disagrees with
  // it would describe a trial this instance is not actually on.
  const trialEnd = license?.trial_end ? new Date(license.trial_end) : null;
  const isOnTrial = trialEnd !== null && trialEnd.getTime() > Date.now();
  let subtitle: string;
  if (isExpired) {
    subtitle = t("subscription.expired.subtitle", { date: formattedDate });
  } else if (isCanceling) {
    subtitle = t("subscription.validUntil.subtitle", { date: formattedDate });
  } else if (isOnTrial) {
    // The trial ending and the first charge are one event, so both halves of
    // this line have to come from the same date.
    const trialDate = formatDateShort(license?.trial_end, locale);
    const daysLeft = trialDaysRemaining(trialEnd);
    subtitle =
      daysLeft <= 0
        ? t("subscription.trialToday.subtitle", { date: trialDate })
        : daysLeft === 1
          ? t("subscription.trialTomorrow.subtitle", { date: trialDate })
          : t("subscription.trialDays.subtitle", {
              days: daysLeft,
              date: trialDate,
            });
  } else if (billing?.status === BillingStatus.UNPAID) {
    // `unpaid` has no scheduled charge — the generic "next payment" line
    // would print a stale `current_period_end` as if a renewal existed.
    subtitle = t("subscription.unpaid.subtitle");
  } else if (billing?.status === BillingStatus.PAST_DUE) {
    // The "next payment" framing lies the other way on past_due: the
    // invoice is OVERDUE, not scheduled — the grace deadline is the date
    // that matters.
    subtitle = t("subscription.pastDue.subtitle", {
      date: formatDateShort(
        billing.grace_ends_at ?? billing.current_period_end,
        locale
      ),
    });
  } else if (billing) {
    subtitle = t("subscription.nextPayment.subtitle", { date: formattedDate });
  } else {
    subtitle = t("subscription.validUntil.subtitle", { date: formattedDate });
  }

  const handleManagePlan = () => {
    // The Stripe portal is gone. Manage Plan is its own page.
    window.location.href = "/admin/billing/manage";
  };

  const handleSyncLicense = async () => {
    setIsSyncing(true);
    try {
      await claimLicense();
      await onRefresh?.();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("toasts.syncLicenseFailed")
      );
    } finally {
      setIsSyncing(false);
    }
  };

  // Trial conversion goes STRAIGHT to checkout: the seats are prefilled
  // with the occupancy, the admin can raise them before paying, and the
  // control plane rejects a stale count with 409 — the frontend re-reads.
  // No synchronous charge and no frontend retry: the webhook is
  // authoritative (a retry ahead of the webhook would double-charge).
  const handleEndTrial = () => {
    onViewCheckout();
  };

  // Only cloud exposes ending a trial early. Self-hosted has no such control.
  const canEndTrialEarly =
    NEXT_PUBLIC_CLOUD_ENABLED && billing?.status === BillingStatus.TRIALING;
  // A canceled subscription's self-serve return is an explicit paid
  // checkout — the same view the trial conversion uses.
  const canResubscribe =
    NEXT_PUBLIC_CLOUD_ENABLED && billing?.status === BillingStatus.CANCELED;
  // A pending cancellation can be lifted until the boundary — the card
  // offers the same /subscription/resume the Manage Plan banner calls.
  const canResume =
    NEXT_PUBLIC_CLOUD_ENABLED &&
    isCanceling === true &&
    billing?.status === BillingStatus.ACTIVE;
  // `unpaid` splits by `seats` — an expired trial (0) goes through
  // the seat-picking checkout; an ex-paid subscription (>0) reactivates,
  // paying a fresh period from today.
  const isUnpaidExpiredTrial =
    NEXT_PUBLIC_CLOUD_ENABLED &&
    billing?.status === BillingStatus.UNPAID &&
    billing.seats === 0;
  const isUnpaidExPaid =
    NEXT_PUBLIC_CLOUD_ENABLED &&
    billing?.status === BillingStatus.UNPAID &&
    (billing.seats ?? 0) > 0;
  // `past_due` keeps product access but carries a debt: the card's CTA is
  // paying the OPEN renewal invoice — the same period-preserving path the
  // Manage Plan banner offers (decision 33).
  const isPastDue =
    NEXT_PUBLIC_CLOUD_ENABLED && billing?.status === BillingStatus.PAST_DUE;
  const { data: openInvoices } = useSWR<InvoiceListResponse>(
    isPastDue ? SWR_KEYS.billingInvoices : null,
    errorHandlingFetcher
  );
  const openInvoice = openInvoices?.invoices.find(
    (invoice) => invoice.status === "open"
  );

  const [isPayingInvoice, setIsPayingInvoice] = useState(false);
  const handlePayOpenInvoice = async () => {
    if (!openInvoice) {
      return;
    }
    setIsPayingInvoice(true);
    try {
      const result = await payInvoice(
        openInvoice.id,
        `${window.location.origin}/admin/billing?yk_return=1`
      );
      // The return polls this charge — the id is created during this
      // request, so it travels through sessionStorage.
      rememberPendingCharge(result.charge_id);
      window.location.href = result.confirmation_url;
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : t("manage.toasts.payInvoiceFailed")
      );
      setIsPayingInvoice(false);
    }
  };

  const [isResuming, setIsResuming] = useState(false);
  const handleResume = async () => {
    setIsResuming(true);
    try {
      await resumeSubscription();
      await onRefresh?.();
      toast.success(t("manage.toasts.resumed"));
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("manage.toasts.resumeFailed")
      );
    } finally {
      setIsResuming(false);
    }
  };

  const [isReactivating, setIsReactivating] = useState(false);
  const handleReactivate = async () => {
    setIsReactivating(true);
    try {
      const { confirmation_url, charge_id } = await reactivateSubscription(
        `${window.location.origin}/admin/billing?yk_return=1`
      );
      if (!confirmation_url) {
        throw new Error(t("manage.toasts.reactivateFailed"));
      }
      rememberPendingCharge(charge_id);
      window.location.href = confirmation_url;
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : t("manage.toasts.reactivateFailed")
      );
      setIsReactivating(false);
    }
  };

  return (
    <Card>
      <ContentAction
        icon={PlanIcon}
        title={planName}
        description={subtitle}
        sizePreset="main-content"
        variant="section"
        padding={0}
        responsive
        rightChildren={
          // `width="full"`: the responsive ContentAction grid gives the right
          // slot a 12rem minimum, so a shrink-wrapped child would hug the
          // slot's LEFT edge and leave a gap to the card's right edge.
          <Section
            flexDirection="column"
            gap={1}
            alignItems="end"
            height="auto"
            width="full"
          >
            {isManualLicenseOnly ? (
              <Text secondaryBody text03 className="text-end">
                {t.rich("subscription.managedBySales.text", {
                  br: () => <br />,
                  link: (chunks) => (
                    <a
                      href="mailto:support@yahont.ai?subject=Billing%20change%20request"
                      className="underline"
                    >
                      {chunks}
                    </a>
                  ),
                })}
              </Text>
            ) : (
              <Section
                flexDirection="row"
                gap={2}
                alignItems="end"
                height="auto"
                width="auto"
              >
                {(canEndTrialEarly || isUnpaidExpiredTrial) && (
                  <Button onClick={handleEndTrial} rightIcon={SvgArrowRight}>
                    {t("subscription.upgradeNow.label")}
                  </Button>
                )}
                {canResubscribe && (
                  <Button onClick={onViewCheckout} rightIcon={SvgArrowRight}>
                    {t("subscription.resubscribe.label")}
                  </Button>
                )}
                {canResume && (
                  <Button
                    onClick={handleResume}
                    disabled={isResuming}
                    rightIcon={SvgArrowRight}
                  >
                    {t("subscription.resume.label")}
                  </Button>
                )}
                {isUnpaidExPaid && (
                  <Button
                    onClick={handleReactivate}
                    disabled={isReactivating}
                    rightIcon={SvgArrowRight}
                  >
                    {t("subscription.payAndRestore.label")}
                  </Button>
                )}
                {isPastDue && openInvoice && (
                  <Button
                    onClick={handlePayOpenInvoice}
                    disabled={isPayingInvoice}
                    rightIcon={SvgArrowRight}
                  >
                    {t("subscription.payNow.label")}
                  </Button>
                )}
                {/* Cloud has no local license to pull. Self-hosted refreshes
                    itself only inside LICENSE_RECLAIM_WINDOW, so a change made
                    earlier in the period needs a manual pull. */}
                {!NEXT_PUBLIC_CLOUD_ENABLED && (
                  <Button
                    disabled={isSyncing}
                    prominence="secondary"
                    onClick={handleSyncLicense}
                  >
                    {isSyncing
                      ? t("subscription.syncing.label")
                      : t("subscription.syncLicense.label")}
                  </Button>
                )}
                <Button
                  prominence={
                    canEndTrialEarly ||
                    canResubscribe ||
                    canResume ||
                    isUnpaidExpiredTrial ||
                    isUnpaidExPaid ||
                    (isPastDue && openInvoice !== undefined)
                      ? "secondary"
                      : "primary"
                  }
                  onClick={handleManagePlan}
                  rightIcon={SvgExternalLink}
                >
                  {t("subscription.managePlan.label")}
                </Button>
              </Section>
            )}
            <Button prominence="tertiary" onClick={onViewPlans}>
              {t("subscription.viewPlanDetails.label")}
            </Button>
          </Section>
        }
      />
    </Card>
  );
}

// ----------------------------------------------------------------------------
// SeatsCard
// ----------------------------------------------------------------------------

function SeatsCard({
  billing,
  license,
  onRefresh,
  disabled,
  hideUpdateSeats,
}: {
  billing?: BillingInformation;
  license?: LicenseStatus;
  onRefresh?: () => Promise<void>;
  disabled?: boolean;
  hideUpdateSeats?: boolean;
}) {
  const t = useTranslations("admin.billing");
  const router = useRouter();
  const { data: usersData } = useUsers({ includeApiKeys: false });
  // occupied_seats comes from the unified backend predicate.
  const { data: occupiedSeatsData } = useOccupiedSeats();

  // Seat enforcement reads the license, so preferring the billing snapshot
  // can render a count the instance would refuse to honor.
  const licensedSeats = license?.has_license ? license.seats : undefined;
  const totalSeats = licensedSeats ?? billing?.seats ?? 0;
  const acceptedUsers =
    usersData?.accepted?.filter((u) => u.is_active).length ?? 0;
  const slackUsers =
    usersData?.slack_users?.filter((u) => u.is_active).length ?? 0;
  const pendingSeats = usersData?.invited?.length ?? 0;
  const occupiedSeats = occupiedSeatsData?.occupied_seats ?? 0;
  // The unified predicate counts unaccepted invitations as occupied, so the
  // plain "active" number is what remains after removing them. The clamp
  // covers an invitation that does not occupy a seat here (the invitee is
  // active in another tenant) — it is still listed as pending.
  const activeSeats = Math.max(0, occupiedSeats - pendingSeats);
  const remainingSeats = Math.max(0, totalSeats - occupiedSeats);

  // On a trial the button is VISIBLE but disabled with the hint — a hidden
  // button does not explain why the feature is missing. Paid seats do not
  // exist on a trial; the server-side limit holds NUM_FREE_TRIAL_USER_INVITES.
  const updateDisabled =
    disabled ||
    !billing ||
    billing.status === BillingStatus.TRIALING ||
    billing.status === BillingStatus.UNPAID ||
    billing.status === BillingStatus.PAST_DUE ||
    billing.status === BillingStatus.CANCELED ||
    // Cancel-pending: an increase would charge money for seats that die
    // at the boundary; a decrease is silently discarded by the cancel.
    billing.cancel_at_period_end;

  return (
    <Card>
      <ContentAction
        title={t("seats.total.label", { count: totalSeats })}
        description={t("seats.breakdown.label", {
          active: activeSeats,
          pending: pendingSeats,
          remaining: remainingSeats,
        })}
        sizePreset="main-content"
        variant="section"
        padding={0}
        responsive
        rightChildren={
          <Section
            flexDirection="row"
            gap={2}
            justifyContent="end"
            height="auto"
            width="full"
          >
            <Button
              prominence="tertiary"
              href="/admin/users"
              icon={SvgExternalLink}
            >
              {t("seats.viewUsers.label")}
            </Button>
            {!hideUpdateSeats && (
              <Button
                disabled={updateDisabled}
                prominence="secondary"
                onClick={() =>
                  router.push("/admin/billing/manage?wizard=seats")
                }
                icon={SvgPlus}
              >
                {t("seats.updateSeats.label")}
              </Button>
            )}
          </Section>
        }
      />
    </Card>
  );
}

// ----------------------------------------------------------------------------
// BillingDetailsView
// ----------------------------------------------------------------------------

interface BillingDetailsViewProps {
  billing?: BillingInformation;
  license?: LicenseStatus;
  onViewPlans: () => void;
  onViewCheckout: () => void;
  onRefresh?: () => Promise<void>;
  isAirGapped?: boolean;
  isManualLicenseOnly?: boolean;
  hasBillingError?: boolean;
  licenseCard?: React.ReactNode;
  isGraceSyncing?: boolean;
}

export default function BillingDetailsView({
  billing,
  license,
  onViewPlans,
  onViewCheckout,
  onRefresh,
  isAirGapped,
  isManualLicenseOnly,
  hasBillingError,
  licenseCard,
  isGraceSyncing,
}: BillingDetailsViewProps) {
  const t = useTranslations("admin.billing");
  const locale = useLocale();
  const expirationState = billing
    ? getExpirationState(billing, locale, license)
    : null;
  const disableBillingActions =
    isAirGapped || hasBillingError || isManualLicenseOnly;

  return (
    <Section gap={4} height="auto" width="full">
      {/* Renewal fetched on arrival while expired. The page renders regardless:
          billing is the one route a lapsed instance must always reach. */}
      {isGraceSyncing && (
        <MessageCard variant="info" title={t("banners.graceSync.title")} />
      )}
      {/* Billing service unreachable banner */}
      {hasBillingError && (
        <MessageCard
          variant="warning"
          title={t("banners.billingUnreachable.title")}
          description={t("banners.billingUnreachable.description")}
        />
      )}

      {/* Air-gapped mode info banner */}
      {isAirGapped && !hasBillingError && !isManualLicenseOnly && (
        <MessageCard
          variant="info"
          title={t("banners.airGapped.title")}
          description={t("banners.airGapped.description")}
        />
      )}

      {/* Expiration banner */}
      {expirationState && (
        <MessageCard
          variant={expirationState.variant}
          title={
            expirationState.variant === "error"
              ? expirationState.daysUntilDeletion
                ? t("banners.expired.withDeletion.title", {
                    days: expirationState.daysUntilDeletion,
                  })
                : t("banners.expired.title")
              : t("banners.expiring.title", {
                  days: expirationState.daysRemaining,
                })
          }
          description={
            expirationState.variant === "error"
              ? expirationState.expirationDate
                ? t("banners.expired.withDate.description", {
                    date: expirationState.expirationDate,
                  })
                : t("banners.expired.description")
              : t("banners.expiring.description", {
                  date: expirationState.expirationDate,
                })
          }
        />
      )}

      {/* Subscription card */}
      {(billing || license?.has_license) && (
        <SubscriptionCard
          billing={billing}
          license={license}
          onViewPlans={onViewPlans}
          onViewCheckout={onViewCheckout}
          isManualLicenseOnly={isManualLicenseOnly}
          onRefresh={onRefresh}
        />
      )}

      {/* License card (inline for manual license users) */}
      {licenseCard}

      {/* Seats card */}
      <SeatsCard
        billing={billing}
        license={license}
        onRefresh={onRefresh}
        disabled={disableBillingActions}
        hideUpdateSeats={isManualLicenseOnly}
      />

      {/* Payment section */}
      {/* TODO: Re-enable payment section when APIs for fetching payment details are implemented */}
      {/* {billing?.payment_method_enabled && !isAirGapped && <PaymentSection billing={billing} />} */}
    </Section>
  );
}
