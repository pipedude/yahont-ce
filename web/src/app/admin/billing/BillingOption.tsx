"use client";

/**
 * One informational tariff card (solo seat / multi seats). Shared by the
 * checkout and the seat-change wizard so both screens describe the same
 * tariff the same way. Informational only — the card carries no click
 * action; the billed amount comes from the catalog, never from here.
 */

import { useTranslations } from "next-intl";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
// The component owns its styles: every route that renders a card needs
// them, and a page-level import is easy to forget.
import "./billing.css";

interface BillingOptionProps {
  /** The tone distinguishes the two tariff variants: the solo seat is
   * green, the multi-seat price is blue. */
  tone: "blue" | "green";
  title: string;
  /** The decimal string ("790.00") — the catalog is the price source. */
  price: string;
}

export default function BillingOption({
  tone,
  title,
  price,
}: BillingOptionProps) {
  const t = useTranslations("admin.billing");

  return (
    <Card className="billing-option" data-tone={tone} padding={0}>
      <Section
        flexDirection="row"
        gap={2}
        height="fit"
        justifyContent="between"
        alignItems="start"
      >
        <Section
          alignItems="start"
          justifyContent="center"
          gap={0}
          height="fit"
          width="fit"
        >
          <Text mainUiAction className="billing-option-title">
            {title}
          </Text>
          <div className="billing-option-price">
            <Text mainContentEmphasis text04>
              {t("checkout.price.label", { price })}
            </Text>
            <Text secondaryBody text03 nowrap>
              {t("checkout.perSeatMonth.label")}
            </Text>
          </div>
        </Section>
      </Section>
    </Card>
  );
}
