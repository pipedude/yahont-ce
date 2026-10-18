"use client";

/**
 * The invoice detail: the positions, EVERY capture attempt (the `charges`
 * array) and the refunded remainder. The open invoice offers the recovery
 * pay — a NEW charge with a NEW key, interactive confirmation_url; the
 * return is served by the ?yk_return=1 flow.
 */

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import useSWR from "swr";
import { Button, Modal, Text } from "@opal/components";
import { toast } from "@opal/layouts";
import { formatDateShort } from "@/lib/dateUtils";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  BillingAccount,
  ChargeAttempt,
  Invoice,
} from "@/lib/billing/types";
import {
  formatCpAmount,
  formatMoney,
  parseAmountToKop,
} from "@/lib/billing/format-money";
import { useDeclineMessage } from "@/lib/billing/cancellation-reasons";
import { payInvoice } from "@/lib/billing/svc";
import { rememberPendingCharge } from "@/lib/billing/pending-charge";

export default function InvoiceDetailModal({
  invoiceId,
  account,
  onClose,
}: {
  invoiceId: string;
  account: BillingAccount | undefined;
  onClose: () => void;
}) {
  const t = useTranslations("admin.billing.manage.invoices");
  const locale = useLocale();
  const declineMessage = useDeclineMessage();
  const { data } = useSWR<Invoice>(
    `${SWR_KEYS.billingInvoices}/${invoiceId}`,
    errorHandlingFetcher
  );

  const [paying, setPaying] = useState(false);

  const handlePay = async () => {
    setPaying(true);
    try {
      const result = await payInvoice(
        invoiceId,
        `${window.location.origin}/admin/billing/manage?yk_return=1`
      );
      // The return polls this charge — the id is created during this
      // request, so it travels through sessionStorage.
      rememberPendingCharge(result.charge_id);
      window.location.href = result.confirmation_url;
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("pay"));
      setPaying(false);
    }
  };

  // Resume the provider checkout of a pending attempt (an
  // off-session 3-DS payment or an abandoned interactive one) — the SAME
  // charge is completed, no new capture is created.
  const handleResume = (attempt: ChargeAttempt) => {
    if (!attempt.confirmation_url) {
      return;
    }
    rememberPendingCharge(attempt.charge_id);
    window.location.href = attempt.confirmation_url;
  };

  // While ANY attempt is in flight the backend refuses a duplicate pay
  // (in-flight guard) — Pay must not be offered at all.
  const hasInFlightAttempt = (data?.charges ?? []).some(
    (charge) => charge.status === "pending"
  );
  // The latest resumable attempt: its button replaces Pay in the
  // footer — the SAME charge is completed, no new capture is created.
  const resumableAttempt = (data?.charges ?? [])
    .filter((charge) => charge.status === "pending" && charge.confirmation_url)
    .at(-1);

  const refundedKop = (data?.charges ?? []).reduce(
    (sum, charge) => sum + parseAmountToKop(charge.refunded_amount ?? "0.00"),
    0
  );

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="md">
        <Modal.Header
          title={data ? `${t("detail")} №${data.number}` : t("detail")}
          onClose={onClose}
        />
        <Modal.Body>
          {!data ? (
            <Text font="secondary-body" color="text-05">
              {t("empty")}
            </Text>
          ) : (
            <div className="flex flex-col gap-4">
              <Text font="secondary-action" color="text-05">
                {t("positions")}
              </Text>
              <div className="flex flex-col gap-1">
                {(data.lines ?? []).map((line) => (
                  <div
                    key={line.description}
                    className="flex items-center justify-between"
                  >
                    <Text font="secondary-body" color="text-03">
                      {`${line.description} × ${line.quantity}`}
                    </Text>
                    <Text font="secondary-body" color="text-02">
                      {formatCpAmount(line.amount)}
                    </Text>
                  </div>
                ))}
              </div>

              {(data.charges ?? []).length > 0 && (
                <div className="flex flex-col gap-2">
                  <Text font="secondary-action" color="text-05">
                    {t("attempts")}
                  </Text>
                  {(data.charges ?? []).map((attempt) => (
                    <div
                      key={attempt.charge_id}
                      className="flex flex-col gap-1 rounded-12 border border-border-01 p-2"
                    >
                      <Text font="secondary-body" color="text-02">
                        {`${formatDateShort(attempt.created_at, locale)} · ${formatCpAmount(
                          attempt.amount
                        )} · ${
                          attempt.status === "succeeded"
                            ? t("status.attemptSucceeded")
                            : attempt.status === "canceled"
                              ? t("status.attemptCanceled")
                              : t("status.attemptPending")
                        }`}
                      </Text>
                      {attempt.status === "canceled" && (
                        <Text font="secondary-body" color="text-05">
                          {declineMessage(attempt.cancellation_reason)}
                        </Text>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {refundedKop > 0 && (
                <Text font="secondary-body" color="text-03">
                  {t("refunded", { amount: formatMoney(refundedKop) })}
                </Text>
              )}

              {account?.email && data.status === "paid" && (
                <Text font="secondary-body" color="text-05">
                  {t("checkSent", { email: account.email })}
                </Text>
              )}
            </div>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onClose}>
            {t("close")}
          </Button>
          {data?.status === "open" &&
            (resumableAttempt ? (
              <Button
                prominence="primary"
                onClick={() => handleResume(resumableAttempt)}
              >
                {t("completePayment")}
              </Button>
            ) : (
              !hasInFlightAttempt && (
                <Button
                  prominence="primary"
                  onClick={handlePay}
                  disabled={paying}
                >
                  {t("pay")}
                </Button>
              )
            ))}
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
