"use client";

/**
 * The Manage Plan route.
 *
 * A ROUTE, not a modal: the seat wizard has its own navigation, the
 * preview state and the deep links after the ЮKassa return
 * (`?yk_return=1&charge=<id>`). Gated tenants MUST reach it —
 * the delinquent client has to be able to pay; the `/admin/billing`
 * allowlist prefix already covers this path.
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { SettingsLayouts, toast } from "@opal/layouts";
import { MessageCard } from "@opal/components";
import { SvgWallet } from "@opal/icons";
import { useDeclineMessage } from "@/lib/billing/cancellation-reasons";
// The seat wizard renders the same tariff cards and content area as the
// checkout; without this import the `.billing-option` rules are absent on
// this route and the cards collapse.
import "../billing.css";
import { invalidateBillingTree } from "./PaymentMethodsSection";
import { useChargeStatusPolling } from "./useChargeStatusPolling";
import { takePendingCharge } from "@/lib/billing/pending-charge";
import ManagePlanOverview from "./ManagePlanOverview";
import PlanChangeWizard from "./PlanChangeWizard";

export default function ManagePlanPage() {
  const t = useTranslations("admin.billing.manage");
  const declineMessage = useDeclineMessage();
  const searchParams = useSearchParams();
  const router = useRouter();

  const [wizardOpen, setWizardOpen] = useState(false);
  // The wizard's step lives here: the header's Back walks the wizard back
  // one step (2 → 1) instead of closing it, and only closes it from step 1.
  const [wizardStep, setWizardStep] = useState<1 | 2>(1);
  const [chargePending, setChargePending] = useState(false);
  const { start } = useChargeStatusPolling();

  // Deep link: /admin/billing/manage?wizard=seats opens the wizard at
  // step 1 (the «Update Seats» entry points).
  useEffect(() => {
    if (searchParams.get("wizard") === "seats") {
      setWizardStep(1);
      setWizardOpen(true);
    }
  }, [searchParams]);

  const openWizard = useCallback(() => {
    setWizardStep(1);
    setWizardOpen(true);
  }, []);
  const closeWizard = useCallback(() => setWizardOpen(false), []);
  const handleBack = useCallback(() => {
    if (!wizardOpen) {
      router.push("/admin/billing");
      return;
    }
    if (wizardStep === 2) {
      setWizardStep(1);
      return;
    }
    setWizardOpen(false);
  }, [router, wizardOpen, wizardStep]);

  // The ЮKassa return: strip the transit params from the URL, poll the
  // charge, invalidate the billing SWR tree. The frontend never repeats the
  // payment and never completes the conversion — the webhook is
  // authoritative (pending is not success).
  useEffect(() => {
    if (searchParams.get("yk_return") !== "1") {
      return;
    }
    // The charge id comes from the URL when the caller could build it in
    // advance, otherwise from sessionStorage — the control plane creates the charge
    // during the pay request, so the id cannot ride the return_url.
    const chargeId = searchParams.get("charge") ?? takePendingCharge();
    router.replace("/admin/billing/manage");
    if (!chargeId) {
      // A binding return carries no charge — refresh the tree so the
      // newly activated method renders (payment_method.active is async).
      void invalidateBillingTree();
      return;
    }
    start(chargeId, (outcome) => {
      if (outcome.kind === "settled" && outcome.charge.status === "succeeded") {
        toast.success(t("toasts.paid"));
      } else if (outcome.kind === "settled") {
        toast.error(declineMessage(outcome.charge.cancellation_reason));
      } else {
        setChargePending(true);
      }
      void invalidateBillingTree();
    });
    // Runs once per mount: the transit params are read before the replace.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgWallet}
        title={t("title")}
        cancel={handleBack}
        divider
      />
      <SettingsLayouts.Body>
        <div className="flex flex-col gap-6">
          {chargePending && (
            <MessageCard
              variant="warning"
              title={t("chargePending.title")}
              description={t("chargePending.description")}
            />
          )}
          {wizardOpen ? (
            <PlanChangeWizard
              step={wizardStep}
              onStepChange={setWizardStep}
              onDone={closeWizard}
            />
          ) : (
            <ManagePlanOverview />
          )}
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
