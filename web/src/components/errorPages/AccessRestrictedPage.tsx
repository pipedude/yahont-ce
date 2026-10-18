"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";
import { Button, useCreateModal } from "@opal/components";
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import DowngradeToCommunityModal from "@/sections/modals/DowngradeToCommunityModal";
import { useUser } from "@/providers/UserProvider";
import { logout } from "@/lib/users/svc";
import { loginPath } from "@/lib/auth/paths";
import { COMMUNITY_URL, NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { useLicense } from "@/hooks/useLicense";
import { useSettings } from "@/lib/settings/hooks";
import { ApplicationStatus } from "@/lib/settings/types";
import Text from "@/refresh-components/texts/Text";
import { SvgLock } from "@opal/icons";

const linkClassName =
  "text-action-selection-05 hover:text-action-selection-06 underline";

// The legacy /tenants/create-subscription-session is gone. The re-payment
// path for a delinquent tenant is the reactivate proxy — it stays reachable
// for a gated tenant by the allowlist.

export default function AccessRestricted() {
  const t = useTranslations("common.errorPages");
  const { data: license } = useLicense();
  const settings = useSettings();
  const { appName } = settings;
  const { isAdmin } = useUser();
  const downgradeModal = useCreateModal();

  // Lands on the held login page: with SSO as the only way in, a reload would
  // sign the user straight back in through the IdP session.
  async function handleLogout() {
    await logout();
    window.location.href = loginPath({ autoRedirectToSso: false });
  }

  const isSeatLimitExceeded =
    settings.application_status === ApplicationStatus.SEAT_LIMIT_EXCEEDED;
  const hadPreviousLicense = license?.has_license === true;
  const showRenewalMessage = NEXT_PUBLIC_CLOUD_ENABLED || hadPreviousLicense;

  function getSeatLimitMessage() {
    const { used_seats, seat_count } = settings;
    return used_seats != null && seat_count != null
      ? t("accessRestricted.seatLimitWithCounts.description", {
          used: used_seats,
          seats: seat_count,
        })
      : t("accessRestricted.seatLimit.description");
  }

  const initialModalMessage = isSeatLimitExceeded
    ? getSeatLimitMessage()
    : showRenewalMessage
      ? NEXT_PUBLIC_CLOUD_ENABLED
        ? t("accessRestricted.subscriptionLapse.description", { appName })
        : t("accessRestricted.licenseLapse.description", { appName })
      : t("accessRestricted.licenseRequired.description", { appName });

  const handleResubscribe = () => {
    // One entry point for every lapsed state: the billing page renders the
    // right CTA itself (Pay now on an open invoice, the seat-picking
    // checkout for canceled / expired trials, reactivate for an ex-paid
    // unpaid). `/admin/billing` is allowlisted for a gated tenant, so the
    // redirect always lands.
    window.location.href = "/admin/billing";
  };

  return (
    <ErrorPageLayout>
      <div className="flex items-center gap-2">
        <Text headingH2>{t("accessRestricted.heading.title")}</Text>
        <SvgLock className="stroke-status-error-05 w-6 h-6" />
      </div>

      <Text text03>{initialModalMessage}</Text>

      {isSeatLimitExceeded ? (
        <>
          <Text text03>
            {t.rich("accessRestricted.seatLimitAdminHint.text", {
              userLink: (chunks) => (
                <Link className={linkClassName} href="/admin/users">
                  {chunks}
                </Link>
              ),
              billingLink: (chunks) => (
                <Link className={linkClassName} href="/admin/billing">
                  {chunks}
                </Link>
              ),
            })}
          </Text>

          <div className="flex flex-row gap-2">
            <Button onClick={handleLogout}>
              {t("accessRestricted.logoutButton.label")}
            </Button>
          </div>
        </>
      ) : NEXT_PUBLIC_CLOUD_ENABLED ? (
        <>
          <Text text03>
            {t("accessRestricted.updatePayment.description", { appName })}
          </Text>

          <Text text03>
            {t("accessRestricted.manageSubscription.description")}
          </Text>

          <div className="flex flex-row gap-2">
            <Button onClick={handleResubscribe}>
              {t("accessRestricted.resubscribeButton.label")}
            </Button>
            <Button prominence="secondary" onClick={handleLogout}>
              {t("accessRestricted.logoutButton.label")}
            </Button>
          </div>
        </>
      ) : (
        <>
          <Text text03>
            {hadPreviousLicense
              ? t("accessRestricted.renewLicense.description", { appName })
              : t("accessRestricted.obtainLicense.description")}
          </Text>

          <Text text03>
            {t.rich("accessRestricted.billingAdminHint.text", {
              hadLicense: hadPreviousLicense ? "true" : "false",
              billingLink: (chunks) => (
                <Link className={linkClassName} href="/admin/billing">
                  {chunks}
                </Link>
              ),
              supportLink: (chunks) => (
                <a className={linkClassName} href="mailto:support@yahont.ai">
                  {chunks}
                </a>
              ),
            })}
          </Text>

          <div className="flex flex-row gap-2">
            <Button onClick={handleLogout}>
              {t("accessRestricted.logoutButton.label")}
            </Button>
            {isAdmin && (
              <Button
                prominence="secondary"
                onClick={() => downgradeModal.toggle(true)}
              >
                {t("accessRestricted.downgradeButton.label")}
              </Button>
            )}
          </div>

          {downgradeModal.isOpen && (
            <DowngradeToCommunityModal
              onClose={() => downgradeModal.toggle(false)}
            />
          )}
        </>
      )}

      <Text text03>
        {t.rich("needHelp.text", {
          communityLink: (chunks) => (
            <InlineExternalLink className={linkClassName} href={COMMUNITY_URL}>
              {chunks}
            </InlineExternalLink>
          ),
        })}
      </Text>
    </ErrorPageLayout>
  );
}
