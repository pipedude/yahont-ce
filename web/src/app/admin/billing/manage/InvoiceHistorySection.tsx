"use client";

/**
 * The invoice history: the table of invoices with the check status as
 * TEXT — ЮKassa does not expose a public receipt URL in the «Чеки от
 * ЮKassa» setup (the receipt goes to the payer's email), so
 * `fiscal_receipt.receipt_url` is not read. The «Возвращено N ₽» line
 * comes from the charges' refunded amounts.
 */

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import useSWR from "swr";
import { Section } from "@/layouts/general-layouts";
import { Button, Text } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import { SvgFileText } from "@opal/icons";
import Card from "@/refresh-components/cards/Card";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  BillingAccount,
  Invoice,
  InvoiceListResponse,
} from "@/lib/billing/types";
import {
  formatCpAmount,
  formatMoney,
  parseAmountToKop,
} from "@/lib/billing/format-money";
import { formatDateShort } from "@/lib/dateUtils";
import InvoiceDetailModal from "./InvoiceDetailModal";
import { SWR_KEYS } from "@/lib/swr-keys";

export default function InvoiceHistorySection() {
  const t = useTranslations("admin.billing.manage");
  const { data } = useSWR<InvoiceListResponse>(
    SWR_KEYS.billingInvoices,
    errorHandlingFetcher
  );
  const [invoiceId, setInvoiceId] = useState<string | null>(null);
  const { data: account } = useSWR<BillingAccount>(
    SWR_KEYS.billingAccount,
    errorHandlingFetcher
  );

  const [openId, setOpenId] = useState<string | null>(null);
  const invoices = data?.invoices ?? [];

  return (
    <Section flexDirection="column" alignItems="stretch" gap={2} height="auto">
      <ContentAction
        title={t("invoices.title")}
        sizePreset="main-content"
        variant="section"
        padding={0}
      />
      {invoices.length === 0 ? (
        <Text font="secondary-body" color="text-05">
          {t("invoices.empty")}
        </Text>
      ) : (
        <div className="flex flex-col gap-2">
          {invoices.map((invoice) => (
            <InvoiceRow
              key={invoice.id}
              invoice={invoice}
              account={account}
              onOpen={() => setInvoiceId(invoice.id)}
            />
          ))}
        </div>
      )}
      {invoiceId && (
        <InvoiceDetailModal
          invoiceId={invoiceId}
          account={account}
          onClose={() => setInvoiceId(null)}
        />
      )}
    </Section>
  );
}

function InvoiceRow({
  invoice,
  account,
  onOpen,
}: {
  invoice: Invoice;
  account: BillingAccount | undefined;
  onOpen: () => void;
}) {
  const t = useTranslations("admin.billing.manage.invoices");
  const locale = useLocale();
  // Human-readable INVOICE status: a raw provider code is not an
  // explanation. `open` means «awaiting payment» — NOT «declined»: a fresh
  // invoice has no attempts at all.
  const invoiceStatusLabel = (status: string): string => {
    if (status === "paid") return t("status.paid");
    if (status === "open") return t("status.open");
    if (status === "void") return t("status.void");
    if (status === "uncollectible") return t("status.uncollectible");
    if (status === "draft") return t("status.draft");
    return status;
  };
  // «Отклонён» is a CHARGE fact, not an invoice status: the badge
  // appears only when an attempt was actually canceled by the provider.
  const hasDeclinedCharge = (invoice.charges ?? []).some(
    (charge) => charge.status === "canceled"
  );
  const refundedKop = (invoice.charges ?? []).reduce(
    (sum, c) => sum + parseAmountToKop(c.refunded_amount ?? "0.00"),
    0
  );

  return (
    <Card data-testid="invoice-row" padding={3}>
      <div className="flex items-center justify-between w-full gap-4">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-3">
            <Text font="secondary-body" color="text-02">
              {formatDateShort(invoice.created_at, locale)}
            </Text>
            <Text font="secondary-body" color="text-02">
              {formatCpAmount(invoice.total)}
            </Text>
            <Text font="secondary-body" color="text-05">
              {invoiceStatusLabel(invoice.status)}
            </Text>
            {hasDeclinedCharge && (
              <Text font="secondary-body" color="text-05">
                {t("status.declined")}
              </Text>
            )}
          </div>
          {/* No receipt LINK by design: ЮKassa does not expose a public
              receipt URL (the «Чеки от ЮKassa» decision) — the receipt goes
              to the payer's email. fiscal_receipt.receipt_url is not read. */}
          {account?.email && invoice.status === "paid" && (
            <Text font="secondary-body" color="text-05">
              {t("checkSent", { email: account.email })}
            </Text>
          )}
          {refundedKop > 0 && (
            <Text font="secondary-body" color="text-03">
              {t("refunded", { amount: formatMoney(refundedKop) })}
            </Text>
          )}
        </div>
        <div className="shrink-0">
          <Button
            prominence="tertiary"
            size="sm"
            icon={SvgFileText}
            onClick={onOpen}
          >
            {t("detail")}
          </Button>
        </div>
      </div>
    </Card>
  );
}
