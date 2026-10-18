"use client";

/**
 * The one payment-method card (one saved card per account): brand, masked
 * number, expiry and Detach. There is nothing to default to — the account
 * never has more than this one active method; replacing it goes through
 * "Replace payment method" instead.
 */

import { useTranslations } from "next-intl";

import { Button } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import { SvgCreditCard } from "@opal/icons";
import Card from "@/refresh-components/cards/Card";
import type { PaymentMethod } from "@/lib/billing/types";

export default function PaymentMethodCard({
  method,
  onDetach,
}: {
  method: PaymentMethod;
  onDetach: (id: string) => void;
}) {
  const t = useTranslations("admin.billing.manage.paymentMethods");

  const brand = method.card_type ?? method.issuer_name ?? method.title ?? "";
  const last4 = method.card_last4 ? `•••• ${method.card_last4}` : "";
  const label = [brand, last4].filter(Boolean).join(" ");
  const expiry =
    method.card_expiry_month && method.card_expiry_year
      ? `${String(method.card_expiry_month).padStart(2, "0")}/${String(
          method.card_expiry_year
        ).slice(-2)}`
      : null;

  return (
    <Card>
      <ContentAction
        icon={SvgCreditCard}
        title={label}
        description={expiry ? t("expiry", { value: expiry }) : undefined}
        sizePreset="main-ui"
        variant="section"
        padding={0}
        responsive
        rightChildren={
          // `justify-end`: the responsive ContentAction grid gives the right
          // slot a 12rem minimum, so a block-level child would hug the slot's
          // LEFT edge.
          <div className="flex w-full justify-end">
            <Button
              prominence="tertiary"
              variant="danger"
              onClick={() => onDetach(method.id)}
            >
              {t("detach")}
            </Button>
          </div>
        }
      />
    </Card>
  );
}
