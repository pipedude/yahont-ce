"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { mutate } from "swr";
import { SettingsLayouts, toast } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { SvgArrowUpCircle, SvgWallet } from "@opal/icons";
import type { IconProps } from "@opal/types";
import {
  useBillingInformation,
  useLicense,
  BillingInformation,
  hasActiveSubscription,
  claimLicense,
} from "@/lib/billing";
import { getChargeStatus } from "@/lib/billing/svc";
import { useDeclineMessage } from "@/lib/billing/cancellation-reasons";
import { takePendingCharge } from "@/lib/billing/pending-charge";
import { invalidateBillingInformation } from "@/lib/billing/information-keys";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useUser } from "@/providers/UserProvider";
import { LinkButton, MessageCard } from "@opal/components";

import PlansView from "./PlansView";
import CheckoutView from "./CheckoutView";
import BillingDetailsView from "./BillingDetailsView";
import LlmPackagesCard from "./LlmPackagesCard";
import DowngradeToCommunityLink from "@/app/admin/billing/DowngradeToCommunityLink";
import LicenseActivationCard from "./LicenseActivationCard";
import "./billing.css";

// sessionStorage key: value is a unix-ms expiry timestamp
const BILLING_ACTIVATING_KEY = "billing_license_activating_until";

// ----------------------------------------------------------------------------
// Types
// ----------------------------------------------------------------------------

type BillingView = "plans" | "details" | "checkout" | null;

interface ViewConfig {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  showBackButton: boolean;
}

// ----------------------------------------------------------------------------
// FooterLinks (inlined)
// ----------------------------------------------------------------------------

const SUPPORT_EMAIL = "support@yahont.ai";

function FooterLinks({
  hasSubscription,
  onActivateLicense,
  hideLicenseLink,
}: {
  hasSubscription?: boolean;
  onActivateLicense?: () => void;
  hideLicenseLink?: boolean;
}) {
  const t = useTranslations("admin.billing");
  const { user } = useUser();
  const licenseText = hasSubscription
    ? t("footer.updateLicenseKey.label")
    : t("footer.activateLicenseKey.label");
  const billingHelpHref = `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(
    `[Billing] support for ${user?.email ?? "unknown"}`
  )}`;

  return (
    <Section flexDirection="row" justifyContent="center" gap={4} height="auto">
      {onActivateLicense && !hideLicenseLink && (
        <>
          <Text secondaryBody text03>
            {t("footer.licenseKeyPrompt.label")}
          </Text>
          <LinkButton onClick={onActivateLicense} external={false}>
            {licenseText}
          </LinkButton>
        </>
      )}
      <DowngradeToCommunityLink />
      <LinkButton href={billingHelpHref}>
        {t("footer.billingHelp.label")}
      </LinkButton>
    </Section>
  );
}

// ----------------------------------------------------------------------------
// BillingPage
// ----------------------------------------------------------------------------

export default function BillingPage() {
  const t = useTranslations("admin.billing");
  const declineMessage = useDeclineMessage();
  const router = useRouter();
  const searchParams = useSearchParams();
  // Start with null view to prevent flash - will be set once data loads
  const [view, setView] = useState<BillingView | null>(null);
  const [showLicenseActivationInput, setShowLicenseActivationInput] =
    useState(false);
  const [licenseCardAutoOpened, setLicenseCardAutoOpened] = useState(false);
  const [viewChangeId, setViewChangeId] = useState(0);
  const [chargePending, setChargePending] = useState(false);
  const timerRef = useRef<number | null>(null);
  const [transitionType, setTransitionType] = useState<
    "expand" | "collapse" | "fade"
  >("fade");
  const [isActivating, setIsActivating] = useState<boolean>(false);

  const {
    data: billingData,
    isLoading: billingLoading,
    error: billingError,
    refresh: refreshBilling,
  } = useBillingInformation();
  const {
    data: licenseData,
    isLoading: licenseLoading,
    refresh: refreshLicense,
  } = useLicense();

  const isLoading = billingLoading || licenseLoading;
  const hasSubscription = billingData && hasActiveSubscription(billingData);
  const billing = hasSubscription ? (billingData as BillingInformation) : null;
  const isSelfHosted = !NEXT_PUBLIC_CLOUD_ENABLED;

  const hasManualLicense = licenseData?.source === "manual_upload";

  // Air-gapped: billing endpoint is unreachable (manual license + connectivity error)
  const isAirGapped = !!(hasManualLicense && billingError);

  // Billing unreachable: auto-fetched license but billing endpoint is unreachable
  const hasBillingError = !!(
    isSelfHosted &&
    licenseData?.has_license &&
    billingError &&
    !hasManualLicense
  );

  // Manual license without an active billing subscription
  // Billing-dependent actions (manage plan, update seats) won't work
  const isManualLicenseOnly = !!(hasManualLicense && !hasSubscription);

  // Set initial view based on subscription status (only once when data first loads).
  // `?upgrade=1` opens the checkout directly: the view is page state, not a
  // route, so the trial surfaces on Manage Plan («Upgrade now» in the trial
  // banner) need this door. The param is consumed and stripped.
  useEffect(() => {
    if (!isLoading && view === null) {
      const shouldShowDetails =
        hasSubscription || (isSelfHosted && licenseData?.has_license);
      if (searchParams.get("upgrade") === "1") {
        setView("checkout");
        router.replace("/admin/billing", { scroll: false });
        return;
      }
      setView(shouldShowDetails ? "details" : "plans");
    }
  }, [
    isLoading,
    hasSubscription,
    isSelfHosted,
    licenseData?.has_license,
    view,
    searchParams,
    router,
  ]);

  // Read activating state from sessionStorage after mount (avoids SSR hydration mismatch)
  useEffect(() => {
    const raw = sessionStorage.getItem(BILLING_ACTIVATING_KEY);
    if (!raw) return;
    if (Number(raw) > Date.now()) {
      setIsActivating(true);
    } else {
      sessionStorage.removeItem(BILLING_ACTIVATING_KEY);
    }
  }, []);

  // Show license activation card when billing is unreachable
  useEffect(() => {
    if (hasBillingError && !showLicenseActivationInput) {
      setLicenseCardAutoOpened(true);
      setShowLicenseActivationInput(true);
    }
  }, [hasBillingError, showLicenseActivationInput]);

  // The ЮKassa return: the checkout return_url carries ?yk_return=1; the
  // charge id travels through sessionStorage (the control plane creates it
  // during the request). Poll the status, toast the outcome, invalidate the
  // billing SWR tree. The frontend never repeats the payment — the webhook
  // is authoritative.
  useEffect(() => {
    if (searchParams.get("yk_return") !== "1") {
      return;
    }
    const chargeId =
      searchParams.get("charge") ??
      sessionStorage.getItem("billing_pending_charge");
    router.replace("/admin/billing", { scroll: false });
    if (!chargeId) {
      return;
    }
    const deadline = Date.now() + 30_000;
    const tick = async () => {
      try {
        const charge = await getChargeStatus(chargeId);
        if (charge.status === "succeeded") {
          toast.success(t("manage.toasts.paid"));
        } else if (charge.status === "canceled") {
          toast.error(declineMessage(charge.cancellation_reason));
        } else if (Date.now() >= deadline) {
          setChargePending(true);
          return;
        } else {
          timerRef.current = window.setTimeout(tick, 2000);
          return;
        }
      } catch {
        // A transport error while polling is not a payment failure.
        timerRef.current = window.setTimeout(tick, 2000);
        return;
      }
      await Promise.all([
        invalidateBillingInformation(),
        mutate(SWR_KEYS.settings),
        mutate(SWR_KEYS.enterpriseSettings),
      ]);
      refreshBilling();
    };
    void tick();
    // Runs once per mount: the transit params are read before the replace.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Handle return from checkout or customer portal

  // Handle return from checkout or customer portal
  useEffect(() => {
    const sessionId = searchParams.get("session_id");

    if (!sessionId) return;

    router.replace("/admin/billing", { scroll: false });

    let cancelled = false;

    const handleBillingReturn = async () => {
      if (!NEXT_PUBLIC_CLOUD_ENABLED) {
        // Retry up to 3 times with 2s backoff. The license may not be available
        // immediately if the payment webhook hasn't finished processing yet
        // (redirect and webhook fire nearly simultaneously).
        let lastError: Error | null = null;
        for (let attempt = 0; attempt < 3; attempt++) {
          if (cancelled) return;
          try {
            // After checkout, exchange session_id for license; after portal, re-sync license
            await claimLicense(sessionId ?? undefined);
            if (cancelled) return;
            refreshLicense();
            // Refresh settings so EE-gated UI (e.g. sidebar) updates immediately.
            router.refresh();
            mutate(SWR_KEYS.settings);
            mutate(SWR_KEYS.enterpriseSettings);
            // Navigate to billing details now that the license is active
            changeView("details");
            lastError = null;
            break;
          } catch (err) {
            lastError = err instanceof Error ? err : new Error("Unknown error");
            if (attempt < 2) {
              await new Promise((resolve) => setTimeout(resolve, 2000));
            }
          }
        }
        if (cancelled) return;
        if (lastError) {
          console.error(
            "Failed to sync license after billing return:",
            lastError
          );
          // Show an activating banner on the plans view and keep retrying in the background.
          sessionStorage.setItem(
            BILLING_ACTIVATING_KEY,
            String(Date.now() + 120_000)
          );
          setIsActivating(true);
          changeView("plans");
        }
      }
      if (!cancelled) refreshBilling();
    };
    handleBillingReturn();

    return () => {
      cancelled = true;
    };
    // changeView intentionally omitted: it only calls stable state setters and the
    // effect runs at most once (when the session_id param is present).
  }, [searchParams, router, refreshBilling, refreshLicense]); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll every 15s while activating, up to 2 minutes, to detect when the license arrives.
  useEffect(() => {
    if (!isActivating) return;

    let requestInFlight = false;

    const intervalId = setInterval(async () => {
      if (requestInFlight) return;
      const raw = sessionStorage.getItem(BILLING_ACTIVATING_KEY);
      if (!raw || Number(raw) <= Date.now()) {
        // Expired — stop immediately without waiting for React cleanup
        clearInterval(intervalId);
        sessionStorage.removeItem(BILLING_ACTIVATING_KEY);
        setIsActivating(false);
        return;
      }
      requestInFlight = true;
      try {
        await claimLicense(undefined);
        sessionStorage.removeItem(BILLING_ACTIVATING_KEY);
        setIsActivating(false);
        refreshLicense();
        refreshBilling();
        // Refresh settings so EE-gated UI (e.g. sidebar) updates immediately.
        router.refresh();
        mutate(SWR_KEYS.settings);
        mutate(SWR_KEYS.enterpriseSettings);
        changeView("details");
      } catch (err) {
        // License not ready yet — keep polling. Log so unexpected failures
        // (network errors, 500s) are distinguishable from expected 404s.
        console.debug("License activation poll: will retry", err);
      } finally {
        requestInFlight = false;
      }
    }, 15_000);

    return () => clearInterval(intervalId);
  }, [isActivating]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRefresh = async () => {
    await Promise.all([
      refreshBilling(),
      isSelfHosted ? refreshLicense() : Promise.resolve(),
    ]);
  };

  // An expired instance still works through grace, so the renewal it is waiting
  // on is fetched on arrival rather than left for the admin to click Sync.
  // Fires once per mount. The endpoint's cooldown absorbs reload loops.
  const [graceSyncAttempted, setGraceSyncAttempted] = useState(false);
  const [isGraceSyncing, setIsGraceSyncing] = useState(false);

  useEffect(() => {
    if (
      !isSelfHosted ||
      graceSyncAttempted ||
      licenseData?.expiry_warning_stage !== "grace"
    ) {
      return;
    }
    setGraceSyncAttempted(true);
    setIsGraceSyncing(true);
    claimLicense(undefined)
      .then(() => handleRefresh())
      .catch((error: unknown) =>
        toast.error(
          error instanceof Error ? error.message : t("toasts.licenseSyncFailed")
        )
      )
      .finally(() => setIsGraceSyncing(false));
  }, [isSelfHosted, graceSyncAttempted, licenseData?.expiry_warning_stage, t]); // eslint-disable-line react-hooks/exhaustive-deps

  // Hide license activation card when billing connectivity is restored (only if auto-opened)
  useEffect(() => {
    if (
      !hasBillingError &&
      !isAirGapped &&
      showLicenseActivationInput &&
      licenseCardAutoOpened &&
      !isLoading
    ) {
      if (billingData && hasActiveSubscription(billingData)) {
        setLicenseCardAutoOpened(false);
        setShowLicenseActivationInput(false);
      }
    }
  }, [
    hasBillingError,
    isAirGapped,
    showLicenseActivationInput,
    licenseCardAutoOpened,
    isLoading,
    billingData,
  ]);

  const handleLicenseActivated = () => {
    refreshLicense();
    refreshBilling();
    // Refresh settings so EE-gated UI (e.g. sidebar) updates immediately.
    router.refresh();
    mutate(SWR_KEYS.settings);
    mutate(SWR_KEYS.enterpriseSettings);
    // Navigate to billing details now that the license is active
    changeView("details");
  };

  // View configuration
  const getViewConfig = (): ViewConfig => {
    if (isLoading || view === null) {
      return {
        icon: SvgWallet,
        title: t("header.plansBilling.title"),
        showBackButton: false,
      };
    }
    switch (view) {
      case "checkout":
        return {
          icon: SvgArrowUpCircle,
          title: t("header.upgradePlan.title"),
          // The checkout is reached from BOTH the details page and the
          // plans list — handleBack routes back to the right one (details
          // when the tenant has an entitlement, plans otherwise).
          showBackButton: true,
        };
      case "plans":
        return {
          icon: hasSubscription ? SvgWallet : SvgArrowUpCircle,
          title: hasSubscription
            ? t("header.viewPlans.title")
            : t("header.upgradePlan.title"),
          showBackButton: !!(
            hasSubscription ||
            (isSelfHosted && licenseData?.has_license)
          ),
        };
      case "details":
        return {
          icon: SvgWallet,
          title: t("header.plansBilling.title"),
          showBackButton: false,
        };
    }
  };

  const viewConfig = getViewConfig();

  // Handle view changes with transition
  const changeView = (newView: "plans" | "details" | "checkout") => {
    if (newView === view) return;
    if (newView === "checkout" && view === "plans") {
      setTransitionType("expand");
    } else if (newView === "plans" && view === "checkout") {
      setTransitionType("collapse");
    } else {
      setTransitionType("fade");
    }
    setViewChangeId((id) => id + 1);
    setView(newView);
  };

  const handleBack = () => {
    const hasEntitlement =
      hasSubscription || (isSelfHosted && licenseData?.has_license);
    if (view === "checkout") {
      changeView(hasEntitlement ? "details" : "plans");
    } else if (view === "plans" && hasEntitlement) {
      changeView("details");
    }
  };

  const renderContent = () => {
    if (isLoading || view === null) return null;

    const animationClass =
      transitionType === "expand"
        ? "billing-view-expand"
        : transitionType === "collapse"
          ? "billing-view-collapse"
          : "billing-view-enter";

    const views: Record<typeof view, React.ReactNode> = {
      checkout: <CheckoutView onAdjustPlan={() => changeView("plans")} />,
      plans: (
        <PlansView
          hasSubscription={!!hasSubscription}
          hasLicense={!!licenseData?.has_license}
          onCheckout={() => changeView("checkout")}
          hideFeatures={showLicenseActivationInput}
        />
      ),
      details: (
        <div className="flex flex-col gap-4">
          <BillingDetailsView
            billing={billing ?? undefined}
            license={licenseData ?? undefined}
            onViewPlans={() => changeView("plans")}
            onViewCheckout={() => changeView("checkout")}
            onRefresh={handleRefresh}
            isAirGapped={isAirGapped}
            isManualLicenseOnly={isManualLicenseOnly}
            hasBillingError={hasBillingError}
            isGraceSyncing={isGraceSyncing}
            licenseCard={
              isManualLicenseOnly ? (
                <LicenseActivationCard
                  isOpen
                  onSuccess={handleLicenseActivated}
                  license={licenseData ?? undefined}
                  onClose={() => {}}
                  hideClose
                />
              ) : undefined
            }
          />
          {/* The LLM packages card: the paying tenant buys
              packages from the billing page. It hides itself outside the
              cloud (no catalog → no card). */}
          <LlmPackagesCard />
        </div>
      ),
    };

    return (
      <div key={viewChangeId} className={`w-full ${animationClass}`}>
        {views[view]}
      </div>
    );
  };

  // Render footer
  const renderFooter = () => {
    if (isLoading || view === null) return null;
    return (
      <>
        {showLicenseActivationInput && !isManualLicenseOnly && (
          <div className="w-full billing-card-enter">
            <LicenseActivationCard
              isOpen={showLicenseActivationInput}
              onSuccess={handleLicenseActivated}
              license={licenseData ?? undefined}
              onClose={() => {
                setLicenseCardAutoOpened(false);
                setShowLicenseActivationInput(false);
              }}
            />
          </div>
        )}
        <FooterLinks
          hasSubscription={!!hasSubscription || !!licenseData?.has_license}
          onActivateLicense={
            isSelfHosted ? () => setShowLicenseActivationInput(true) : undefined
          }
          hideLicenseLink={
            isManualLicenseOnly ||
            showLicenseActivationInput ||
            (view === "plans" &&
              (!!hasSubscription || !!licenseData?.has_license))
          }
        />
      </>
    );
  };

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={viewConfig.icon}
        title={viewConfig.title}
        cancel={viewConfig.showBackButton && handleBack}
        divider
      />
      <SettingsLayouts.Body>
        <div className="flex flex-col items-center gap-6">
          {isActivating && (
            <MessageCard
              variant="warning"
              title={t("activatingBanner.title")}
              description={t("activatingBanner.description")}
              onClose={() => {
                sessionStorage.removeItem(BILLING_ACTIVATING_KEY);
                setIsActivating(false);
              }}
            />
          )}
          {chargePending && (
            <MessageCard
              variant="warning"
              title={t("chargePending.title")}
              description={t("chargePending.description")}
              onClose={() => setChargePending(false)}
            />
          )}
          {renderContent()}
          {renderFooter()}
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
