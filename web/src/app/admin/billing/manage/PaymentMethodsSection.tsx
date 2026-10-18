"use client";

/**
 * The payment-methods section: one saved card per account plus the
 * zero-amount binding that replaces it — the ONLY binding without a charge
 * at launch. The method type is picked in a modal (ЮKassa binds each type
 * on its own page); the binding page returns to ?yk_return=1, where the
 * billing service webhook has already retired the old method and made the new
 * one default, and the billing SWR tree is invalidated to pick it up.
 */

import { useState } from "react";
import { useTranslations } from "next-intl";
import { mutate } from "swr";
import { ContentAction } from "@opal/layouts";
import { Button, Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { invalidateBillingInformation } from "@/lib/billing/information-keys";
import { BillingStatus, type PaymentMethod } from "@/lib/billing/types";
import { useBillingInformation } from "@/hooks/useBillingInformation";
import PaymentMethodCard from "./PaymentMethodCard";
import PaymentMethodBindModal from "./PaymentMethodBindModal";
import PaymentMethodDetachModal from "./PaymentMethodDetachModal";

/** Invalidate the billing SWR tree after any mutation.
 * `settings` is mandatory: application_status drives the product gating
 * wrapper, and without the refresh a gated client stays blocked after a
 * successful payment.
 *
 * The billing-information entry goes through `invalidateBillingInformation()`
 * — it covers the deployment-specific key the overview actually reads
 * (cloud reads one key and the old invalidator mutated the other). */
export async function invalidateBillingTree(): Promise<void> {
  await Promise.all([
    invalidateBillingInformation(),
    mutate(SWR_KEYS.billingPaymentMethods),
    mutate(SWR_KEYS.billingInvoices),
    mutate(SWR_KEYS.billingAccount),
    // The seat number lives in its own entry and never self-heals
    // (`revalidateIfStale: false`): a plan/seats mutation must refresh it
    // explicitly, or the billing screens keep a pre-mutation minimum.
    mutate(SWR_KEYS.occupiedSeats),
    mutate(SWR_KEYS.settings),
    mutate(SWR_KEYS.enterpriseSettings),
  ]);
}

export default function PaymentMethodsSection() {
  const t = useTranslations("admin.billing.manage.paymentMethods");
  const { data } = useSWR<{ payment_methods: PaymentMethod[] }>(
    SWR_KEYS.billingPaymentMethods,
    errorHandlingFetcher
  );

  const methods = data?.payment_methods ?? [];
  const { data: billing } = useBillingInformation();

  // The detach goes through a real modal (not window.confirm): the account
  // keeps ONE method, so removing it strands the next renewal — the modal
  // says that and offers "Replace instead" as the non-destructive exit.
  const [detachId, setDetachId] = useState<string | null>(null);

  // A scheduled charge exists only for active/past_due (the period-end
  // renewal). Trialing has no autopay pending and canceled renews nothing.
  // The union is narrowed manually: `"status" in billing` keeps out the
  // bare SubscriptionStatus shape.
  const renewsAt =
    billing &&
    "status" in billing &&
    (billing.status === BillingStatus.ACTIVE ||
      billing.status === BillingStatus.PAST_DUE)
      ? billing.current_period_end
      : null;

  // The only binding without a charge — the method type is
  // picked in a modal, the ЮKassa binding page returns through
  // ?yk_return=1.
  const [bindOpen, setBindOpen] = useState(false);

  return (
    <Section flexDirection="column" alignItems="stretch" gap={2} height="auto">
      <ContentAction
        title={t("title")}
        sizePreset="main-content"
        variant="section"
        padding={0}
      />
      {methods.length === 0 ? (
        <Text font="secondary-body" color="text-05">
          {t("empty")}
        </Text>
      ) : (
        <div className="flex flex-col gap-2">
          {methods.map((method) => (
            <PaymentMethodCard
              key={method.id}
              method={method}
              onDetach={setDetachId}
            />
          ))}
        </div>
      )}
      <div className="flex flex-col gap-1">
        <div>
          <Button prominence="secondary" onClick={() => setBindOpen(true)}>
            {t("replace")}
          </Button>
        </div>
        <Text font="secondary-body" color="text-05">
          {t("replaceHint")}
        </Text>
      </div>
      {bindOpen && (
        <PaymentMethodBindModal onClose={() => setBindOpen(false)} />
      )}
      {detachId && (
        <PaymentMethodDetachModal
          methodId={detachId}
          renewsAt={renewsAt}
          // Modal → modal: both are independent siblings, so "Replace"
          // unmounts the detach dialog and mounts the binding one.
          onReplace={() => {
            setDetachId(null);
            setBindOpen(true);
          }}
          onClose={() => setDetachId(null)}
        />
      )}
    </Section>
  );
}
