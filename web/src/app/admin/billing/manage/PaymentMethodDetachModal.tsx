"use client";

/**
 * The detach confirmation: the account keeps ONE saved method,
 * so detaching it leaves the next renewal with nothing to charge — the
 * modal states the grace→gating consequence explicitly and offers the
 * replace flow as the non-destructive exit instead of a bare
 * window.confirm.
 */

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button, Modal, Text } from "@opal/components";
import { toast } from "@opal/layouts";
import { formatDateShort } from "@/lib/dateUtils";
import { deletePaymentMethod } from "@/lib/billing/svc";
import { invalidateBillingTree } from "./PaymentMethodsSection";

export default function PaymentMethodDetachModal({
  methodId,
  // Non-null only when a charge is actually scheduled against the method
  // (active/past_due → the period-end renewal). Trialing has no autopay
  // pending and canceled renews nothing, so both get the generic text.
  renewsAt,
  onReplace,
  onClose,
}: {
  methodId: string;
  renewsAt: string | null;
  onReplace: () => void;
  onClose: () => void;
}) {
  const t = useTranslations("admin.billing.manage.paymentMethods.detachModal");
  const locale = useLocale();
  const tt = useTranslations("admin.billing.manage.toasts");

  const [submitting, setSubmitting] = useState(false);

  const handleDetach = async () => {
    setSubmitting(true);
    try {
      await deletePaymentMethod(methodId);
      await invalidateBillingTree();
      toast.success(tt("pmDetached"));
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : tt("detachFailed"));
      setSubmitting(false);
    }
  };

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="sm">
        <Modal.Header title={t("title")} onClose={onClose} />
        <Modal.Body>
          <Text font="secondary-body" color="text-03">
            {renewsAt
              ? t("bodyScheduled", { date: formatDateShort(renewsAt, locale) })
              : t("bodyNoCharge")}
          </Text>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onClose}>
            {t("back")}
          </Button>
          <Button prominence="secondary" onClick={onReplace}>
            {t("replace")}
          </Button>
          <Button
            prominence="primary"
            variant="danger"
            disabled={submitting}
            onClick={handleDetach}
          >
            {t("detach")}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
