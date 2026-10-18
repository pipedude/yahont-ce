"use client";

/**
 * The refund-request modal: a reason and a comment. The client does NOT
 * pick the kind, the amount or the charge — the operator assigns the kind
 * at effect confirmation, the amount defaults to the full remainder of the
 * latest refundable payment.
 *
 * Two mandatory warnings: the service refusal is the subscription CANCEL
 * (the access stays until the paid period ends, the period is not
 * refunded), and the money returns to the ORIGINAL payment method.
 */

import { useState } from "react";
import { useTranslations } from "next-intl";
import { mutate } from "swr";
import {
  Button,
  InputSingleSelect,
  InputTypeIn,
  Modal,
  Text,
} from "@opal/components";
import { toast } from "@opal/layouts";
import { SWR_KEYS } from "@/lib/swr-keys";
import { createRefundRequest } from "@/lib/billing/svc";

/** Mirrors the control plane's CLIENT_REFUND_REASONS. */
const REASONS = ["erroneousPayment", "serviceQuality", "other"] as const;
type RefundReason = (typeof REASONS)[number];

const REASON_CODES = {
  erroneousPayment: "erroneous_payment",
  serviceQuality: "service_quality",
  other: "other",
} satisfies Record<RefundReason, string>;

export default function RefundRequestModal({
  onClose,
}: {
  onClose: () => void;
}) {
  const t = useTranslations("admin.billing.manage");

  const [reason, setReason] = useState<RefundReason | null>(null);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    if (reason === null) {
      return;
    }
    setSubmitting(true);
    try {
      await createRefundRequest({
        reason_code: REASON_CODES[reason],
        comment: comment || null,
      });
      await mutate(SWR_KEYS.billingRefundRequests);
      toast.success(t("toasts.refundRequested"));
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("refunds.submit"));
      setSubmitting(false);
    }
  };

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="sm">
        <Modal.Header title={t("refunds.request")} onClose={onClose} />
        <Modal.Body>
          <div className="flex flex-col gap-4">
            <Text font="secondary-body" color="text-02">
              {t("refunds.reasonLabel")}
            </Text>
            <InputSingleSelect
              value={reason ?? ""}
              onValueChange={(value) => {
                // The options are exactly the REASONS entries, which mirror
                // the control plane's CLIENT_REFUND_REASONS.
                const match = REASONS.find((item) => item === value);
                setReason(match ?? null);
              }}
              placeholder={t("refunds.reasonLabel")}
              options={REASONS.map((item) => ({
                value: item,
                title: t(`refunds.reasons.${item}`),
              }))}
            />

            <Text font="secondary-body" color="text-05">
              {t("refunds.cancelHint")}
            </Text>

            <InputTypeIn
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder={t("refunds.commentLabel")}
            />

            <Text font="secondary-body" color="text-05">
              {t("refunds.sameMethodHint")}
            </Text>
          </div>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onClose}>
            {t("cancelModal.back")}
          </Button>
          <Button
            prominence="primary"
            onClick={submit}
            disabled={reason === null || submitting}
          >
            {t("refunds.submit")}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
