"use client";

/**
 * The cancellation modal: the reason survey feeds the billing audit
 * trail; the access deadline is stated explicitly — the subscription
 * stays until the period end (cancel_at_period_end) and the resume works
 * until that date without data loss.
 */

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button, InputSingleSelect, Modal, Text } from "@opal/components";
import { InputTypeIn } from "@opal/components";
import { toast } from "@opal/layouts";
import { formatDateShort } from "@/lib/dateUtils";
import { cancelSubscription } from "@/lib/billing/svc";
import type { CancelReason } from "@/lib/billing/types";
import { invalidateBillingTree } from "./PaymentMethodsSection";

const REASON_CODES: CancelReason[] = [
  "too_expensive",
  "missing_features",
  "switched_service",
  "not_using",
  "technical_issues",
  "temporary_pause",
  "other",
];

export default function CancelSubscriptionModal({
  accessUntil,
  onClose,
}: {
  accessUntil: string | null;
  onClose: () => void;
}) {
  const t = useTranslations("admin.billing.manage.cancelModal");
  const locale = useLocale();
  const tt = useTranslations("admin.billing.manage.toasts");

  const [reason, setReason] = useState<CancelReason | null>(null);
  const [reasonText, setReasonText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleContinue = async () => {
    if (reason === null) {
      return;
    }
    setSubmitting(true);
    try {
      await cancelSubscription({
        reason_code: reason,
        // The free-text comment is only meaningful for «Другое».
        reason_text: reason === "other" ? reasonText || null : null,
      });
      // The cancel flips cancel_at_period_end — without the invalidation the
      // overview keeps the pre-cancel snapshot and never shows the banner
      // (the flag would be set but the UI would not reflect it).
      await invalidateBillingTree();
      toast.success(tt("cancelScheduled"));
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("title"));
      setSubmitting(false);
    }
  };

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="sm">
        <Modal.Header title={t("title")} onClose={onClose} />
        <Modal.Body>
          <div className="flex flex-col gap-4">
            <Text font="secondary-body" color="text-02">
              {t("surveyLabel")}
            </Text>
            <InputSingleSelect
              value={reason ?? ""}
              onValueChange={(value) => {
                // The options are exactly the REASON_CODES entries, so a
                // match IS a CancelReason — no assertion needed.
                const match = REASON_CODES.find((code) => code === value);
                setReason(match ?? null);
              }}
              placeholder={t("reasonLabel")}
              options={REASON_CODES.map((code) => ({
                value: code,
                title: t(`reasons.${code}`),
              }))}
            />
            {reason === "other" && (
              <InputTypeIn
                value={reasonText}
                onChange={(e) => setReasonText(e.target.value)}
                placeholder={t("otherPlaceholder")}
              />
            )}
            <Text font="secondary-body" color="text-03">
              {t("accessUntil", {
                date: accessUntil ? formatDateShort(accessUntil, locale) : "",
              })}
            </Text>
          </div>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onClose}>
            {t("back")}
          </Button>
          <Button
            prominence="primary"
            variant="danger"
            disabled={reason === null || submitting}
            onClick={handleContinue}
          >
            {t("continue")}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
