"use client";

/**
 * The wizard step 2: the preview for an increase (the proration lines, the
 * consent on recurring charges — a ЮKassa requirement, the payment) or the
 * schedule screen for a decrease (NO payment block, no consent).
 * `scheduled: true` and `applied: true` are different outcomes and the UI
 * says so explicitly.
 *
 * The layout mirrors the checkout card: the same header, content area and
 * footer (consent next to the primary action).
 */

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button, Divider, InputCheckbox, Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { toast } from "@opal/layouts";
import Card from "@/refresh-components/cards/Card";
import { SvgUsers } from "@opal/icons";
import { formatDateShort } from "@/lib/dateUtils";
import type { ProrationPreview } from "@/lib/billing/types";
import { formatCpAmount, formatMoney } from "@/lib/billing/format-money";
import { billableAmountKop, type PlanModel } from "@/lib/billing/plan-catalog";
import { updatePlan } from "@/lib/billing/svc";
import { invalidateBillingTree } from "./PaymentMethodsSection";
import { rememberPendingCharge } from "@/lib/billing/pending-charge";

export default function PlanChangeStep2({
  preview,
  quantity,
  was,
  pendingDecrease,
  plan,
  anchorDate,
  onDone,
}: {
  preview: ProrationPreview | null;
  quantity: number;
  was: number;
  /** Non-null means a decrease is already scheduled — a same-quantity
   * submit then means «cancel it», not a payment and not a new plan. */
  pendingDecrease: number | null;
  /** The catalog plan — the recurring sums (Was / Becomes / the anchor
   * note) follow the control plane's rule through `billableAmountKop`, never
   * `seats × price`: one seat bills the solo price. They must also never
   * read the proration total, which is the amount due NOW. */
  plan: PlanModel | null;
  anchorDate: string | null;
  onDone: () => void;
}) {
  const t = useTranslations("admin.billing.manage.wizard");
  const locale = useLocale();
  const tManage = useTranslations("admin.billing.manage");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);

  const isIncrease = (preview?.requires_payment ?? false) === true;
  // quantity == was: the no-change screen — «cancel the planned decrease»
  // when one exists (the only reason step 1 let this through). Neither
  // the increase nor the decrease copy fits it.
  const isNoChange = quantity === was;

  const submit = async () => {
    if (!preview) {
      return;
    }
    setBusy(true);
    try {
      const result = await updatePlan({
        quantity,
        plan_code: "business",
        period: "monthly",
        confirm_total: preview.total,
        return_url: `${window.location.origin}/admin/billing/manage?yk_return=1`,
      });
      if (
        result.requires_payment &&
        result.confirmation_url &&
        result.charge_id
      ) {
        // The interactive payment — the return is served by the
        // ?yk_return=1 flow; the webhook is authoritative. The charge id
        // travels through sessionStorage: the control plane creates the
        // charge during this request, so it cannot ride the return_url.
        rememberPendingCharge(result.charge_id);
        window.location.href = result.confirmation_url;
        return;
      }
      await invalidateBillingTree();
      if (isNoChange) {
        // applied:true + scheduled:false + no `charged` — the no-change
        // answer. Saying «Paid» here told the stand user a payment had
        // happened on a pure no-op (audit, 3→3).
        toast.success(tManage("toasts.decreaseCanceled"));
      } else if (result.scheduled) {
        // Answer D: planned, NOT applied — the UI must not say «применено».
        // The same tokens the preview above renders: the toast used to
        // read "From  0 seats will be paid instead of 3" (audit 2.8.2).
        toast.success(
          t("decreaseNote", {
            date: formatDateShort(anchorDate, locale),
            planned: quantity,
            was,
          })
        );
      } else {
        toast.success(t("paid", { amount: result.charged ?? "" }));
      }
      onDone();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("pay"));
      setBusy(false);
    }
  };

  // Both guards are the same kind: step 1 renders its cards from the
  // catalog, so reaching step 2 without it is not a state the UI can show
  // meaningfully — and every sum below needs it.
  if (!preview || !plan) {
    return null;
  }

  return (
    <Card padding={0} gap={0} alignItems="stretch">
      {/* Header — the same shape as the checkout card header. The page's
          Back steps back to step 1 (the card carries no duplicate). */}
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
            {t("step2Title")}
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
          <Section
            flexDirection="row"
            gap={3}
            alignItems="center"
            justifyContent="start"
            wrap
            height="auto"
          >
            <Section
              flexDirection="column"
              alignItems="start"
              gap={0}
              height="auto"
              width="auto"
            >
              <Text font="secondary-action" color="text-05">
                {t("was")}
              </Text>
              <Text font="main-ui-action">
                {t("seatsWithPrice", {
                  seats: was,
                  amount: formatMoney(billableAmountKop(was, plan)),
                })}
              </Text>
            </Section>
            <Text font="main-ui-action">→</Text>
            <Section
              flexDirection="column"
              alignItems="start"
              gap={0}
              height="auto"
              width="auto"
            >
              <Text font="secondary-action" color="text-05">
                {t("becomes")}
              </Text>
              <Text font="main-ui-action">
                {t("seatsWithPrice", {
                  seats: quantity,
                  amount: formatMoney(billableAmountKop(quantity, plan)),
                })}
              </Text>
            </Section>
          </Section>

          <Divider paddingParallel={0} paddingPerpendicular={0} />

          <Section
            flexDirection="column"
            alignItems="stretch"
            gap={2}
            height="auto"
          >
            <Text font="secondary-action" color="text-05">
              {t("calculation")}
            </Text>
            <Card padding={3}>
              <Section
                flexDirection="column"
                alignItems="stretch"
                gap={2}
                height="auto"
              >
                {(preview.lines ?? []).map((line, index) => (
                  <Section
                    key={`${line.description}-${index}`}
                    flexDirection="row"
                    justifyContent="between"
                    alignItems="center"
                    gap={2}
                    height="auto"
                  >
                    <Text font="secondary-body" color="text-03">
                      {line.description}
                    </Text>
                    <Text
                      font="secondary-body"
                      color="text-02"
                      wordWrap="whitespace-nowrap"
                    >
                      {formatCpAmount(line.amount)}
                    </Text>
                  </Section>
                ))}
                {/* «To pay now» belongs to an increase only: a decrease is
                    scheduled, not paid — showing the label with 0,00 ₽ tells
                    the admin a payment is expected. */}
                {isNoChange ? (
                  <Text font="secondary-body" color="text-03">
                    {t("cancelDecreaseNote", {
                      planned: pendingDecrease ?? was,
                      was,
                    })}
                  </Text>
                ) : isIncrease ? (
                  <>
                    <Divider paddingParallel={0} paddingPerpendicular={0} />
                    <Section
                      flexDirection="row"
                      justifyContent="between"
                      alignItems="center"
                      gap={2}
                      height="auto"
                    >
                      <Text font="main-ui-action">{t("toPayNow")}</Text>
                      <Text font="main-ui-action" wordWrap="whitespace-nowrap">
                        {formatCpAmount(preview.total)}
                      </Text>
                    </Section>
                    <Text font="secondary-body" color="text-05">
                      {t("vatNote")}
                    </Text>
                  </>
                ) : (
                  <Text font="secondary-body" color="text-03">
                    {t("decreaseNote", {
                      date: formatDateShort(anchorDate, locale),
                      planned: quantity,
                      was,
                    })}
                  </Text>
                )}
              </Section>
            </Card>
          </Section>

          {anchorDate && !isNoChange && (
            <Text font="secondary-body" color="text-03">
              {t("anchorNote", {
                date: formatDateShort(anchorDate, locale),
                amount: formatMoney(billableAmountKop(quantity, plan)),
              })}
            </Text>
          )}
        </Section>
      </div>

      {/* Footer */}
      <Section
        className="flex-col items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-2"
        padding={4}
        height="auto"
      >
        {isIncrease ? (
          <div className="flex items-center gap-2">
            <InputCheckbox checked={consent} onCheckedChange={setConsent} />
            <Text font="secondary-body" color="text-03">
              {t("consent")}
            </Text>
          </div>
        ) : (
          <div />
        )}
        <div className="w-full sm:w-auto">
          <Button
            prominence="primary"
            onClick={submit}
            disabled={busy || (isIncrease && !consent)}
            width="full"
          >
            {isNoChange
              ? t("cancelDecrease")
              : isIncrease
                ? t("pay", { amount: formatCpAmount(preview.total) })
                : t("schedule")}
          </Button>
        </div>
      </Section>
    </Card>
  );
}
