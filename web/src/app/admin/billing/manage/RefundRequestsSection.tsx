"use client";

/**
 * The client refund-request statuses: the AGGREGATE status and the amount
 * only — the execution channel, the order numbers and the
 * money_returned-vs-effect state never leave the control plane. But the status MUST
 * be shown: a blind spot generates support tickets and chargebacks.
 */

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import useSWR from "swr";
import { Section } from "@/layouts/general-layouts";
import { Button, Text } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import Card from "@/refresh-components/cards/Card";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { RefundRequestListResponse } from "@/lib/billing/types";
import { formatMoney } from "@/lib/billing/format-money";
import { formatDateShort } from "@/lib/dateUtils";

import RefundRequestModal from "./RefundRequestModal";

export default function RefundRequestsSection() {
  const t = useTranslations("admin.billing.manage");
  const locale = useLocale();
  const { data } = useSWR<RefundRequestListResponse>(
    SWR_KEYS.billingRefundRequests,
    errorHandlingFetcher
  );

  const [modalOpen, setModalOpen] = useState(false);

  const requests = data?.requests ?? [];

  return (
    <Section flexDirection="column" alignItems="stretch" gap={2} height="auto">
      <ContentAction
        title={t("refunds.title")}
        sizePreset="main-content"
        variant="section"
        padding={0}
      />
      {requests.length === 0 ? (
        <Text font="secondary-body" color="text-05">
          {t("refunds.empty")}
        </Text>
      ) : (
        <div className="flex flex-col gap-2">
          {requests.map((request) => (
            <Card key={request.request_id} padding={3}>
              <div className="flex flex-wrap items-center gap-3">
                <Text font="secondary-body" color="text-02">
                  {`${t("refunds.number")} ${request.number}`}
                </Text>
                <Text font="secondary-body" color="text-02">
                  {formatMoney(request.amount_kop)}
                </Text>
                <Text font="secondary-body" color="text-05">
                  {request.status}
                </Text>
                <Text font="secondary-body" color="text-05">
                  {formatDateShort(request.created_at, locale)}
                </Text>
              </div>
            </Card>
          ))}
        </div>
      )}
      <div>
        <Button prominence="secondary" onClick={() => setModalOpen(true)}>
          {t("refunds.request")}
        </Button>
      </div>

      {modalOpen && <RefundRequestModal onClose={() => setModalOpen(false)} />}
    </Section>
  );
}
