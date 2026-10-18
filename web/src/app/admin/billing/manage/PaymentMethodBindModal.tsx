"use client";

/**
 * The bind/replace modal: ЮKassa binds each method TYPE on its
 * own zero-amount page — the choice is made here, before the binding
 * object is created. Only the types ЮKassa accepts on POST
 * /v3/payment_methods are offered (bank_card, sbp); the other
 * autopay-capable methods save only during a real payment.
 */

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button, InputSingleSelect, Modal, Text } from "@opal/components";
import { toast } from "@opal/layouts";
import { startPaymentMethodBinding } from "@/lib/billing/svc";

const BINDABLE_TYPES = ["bank_card", "sbp"] as const;
type BindableType = (typeof BINDABLE_TYPES)[number];

export default function PaymentMethodBindModal({
  onClose,
}: {
  onClose: () => void;
}) {
  const t = useTranslations("admin.billing.manage.paymentMethods.bindModal");

  const [methodType, setMethodType] = useState<BindableType>("bank_card");
  const [submitting, setSubmitting] = useState(false);

  const handleContinue = async () => {
    setSubmitting(true);
    try {
      const binding = await startPaymentMethodBinding(
        `${window.location.origin}/admin/billing/manage?yk_return=1`,
        methodType
      );
      window.location.href = binding.confirmation_url;
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
            <InputSingleSelect
              value={methodType}
              onValueChange={(value) => {
                // The options are exactly the BINDABLE_TYPES entries, so a
                // match IS a BindableType — no assertion needed.
                const match = BINDABLE_TYPES.find((code) => code === value);
                if (match) {
                  setMethodType(match);
                }
              }}
              placeholder={t("methodLabel")}
              options={BINDABLE_TYPES.map((code) => ({
                value: code,
                title: t(`options.${code}`),
              }))}
            />
            <Text font="secondary-body" color="text-03">
              {t(`hints.${methodType}`)}
            </Text>
          </div>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onClose}>
            {t("back")}
          </Button>
          <Button
            prominence="primary"
            disabled={submitting}
            onClick={handleContinue}
          >
            {t("continue")}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
