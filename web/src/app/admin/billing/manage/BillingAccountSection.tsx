"use client";

/**
 * The payer requisites section: the kind (individual / legal
 * entity), the email for receipts, the name and — for a legal entity —
 * the INN/KPP/legal address that go into the receipt. The
 * payment methods are NOT hidden for a legal entity: it pays by card or
 * SBP with auto-payments like an individual.
 */

import { useState } from "react";
import useSWR, { mutate } from "swr";
import { useTranslations } from "next-intl";
import { Section } from "@/layouts/general-layouts";
import { Button, InputTypeIn, Text } from "@opal/components";
import { ContentAction, InputVertical, toast } from "@opal/layouts";
import Card from "@/refresh-components/cards/Card";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { BillingAccount, BillingAccountPatch } from "@/lib/billing/types";
import { getBillingAccount, updateBillingAccount } from "@/lib/billing/svc";

export default function BillingAccountSection() {
  const t = useTranslations("admin.billing.manage");
  const { data } = useSWR<BillingAccount>(
    SWR_KEYS.billingAccount,
    errorHandlingFetcher
  );

  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<BillingAccountPatch>({});

  if (!data) {
    return null;
  }

  const isLegal = data.kind === "legal_entity";

  const startEdit = () => {
    setDraft({
      kind: data.kind,
      email: data.email,
      phone: data.phone,
      display_name: data.display_name,
      inn: data.inn,
      kpp: data.kpp,
      legal_address: data.legal_address,
    });
    setEditing(true);
  };

  const cancelEdit = () => setEditing(false);

  const save = async () => {
    setSaving(true);
    try {
      await updateBillingAccount(draft);
      await mutate(SWR_KEYS.billingAccount);
      toast.success(t("toasts.accountSaved"));
      setEditing(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("account.save"));
    } finally {
      setSaving(false);
    }
  };

  if (editing) {
    return (
      <Section
        flexDirection="column"
        alignItems="stretch"
        gap={2}
        height="auto"
      >
        <ContentAction
          title={t("account.title")}
          sizePreset="main-content"
          variant="section"
          padding={0}
        />
        <Card>
          <Section
            flexDirection="column"
            alignItems="stretch"
            gap={3}
            height="auto"
          >
            <InputVertical title={t("account.email")} withLabel>
              <InputTypeIn
                value={draft.email ?? data.email ?? ""}
                onChange={(e) => setDraft({ ...draft, email: e.target.value })}
              />
            </InputVertical>
            <InputVertical title={t("account.name")} withLabel>
              <InputTypeIn
                value={draft.display_name ?? data.display_name ?? ""}
                onChange={(e) =>
                  setDraft({ ...draft, display_name: e.target.value })
                }
              />
            </InputVertical>
            <InputVertical title={t("account.phone")} withLabel>
              <InputTypeIn
                value={draft.phone ?? data.phone ?? ""}
                onChange={(e) => setDraft({ ...draft, phone: e.target.value })}
              />
            </InputVertical>
            {isLegal && (
              <>
                <InputVertical title={t("account.inn")} withLabel>
                  <InputTypeIn
                    value={draft.inn ?? data.inn ?? ""}
                    onChange={(e) =>
                      setDraft({ ...draft, inn: e.target.value })
                    }
                  />
                </InputVertical>
                <InputVertical title={t("account.kpp")} withLabel>
                  <InputTypeIn
                    value={draft.kpp ?? data.kpp ?? ""}
                    onChange={(e) =>
                      setDraft({ ...draft, kpp: e.target.value })
                    }
                  />
                </InputVertical>
                <InputVertical title={t("account.legalAddress")} withLabel>
                  <InputTypeIn
                    value={draft.legal_address ?? data.legal_address ?? ""}
                    onChange={(e) =>
                      setDraft({ ...draft, legal_address: e.target.value })
                    }
                  />
                </InputVertical>
              </>
            )}
            <div className="flex gap-2">
              <Button prominence="primary" onClick={save} disabled={saving}>
                {t("account.save")}
              </Button>
              <Button prominence="secondary" onClick={cancelEdit}>
                {t("account.cancel")}
              </Button>
            </div>
          </Section>
        </Card>
      </Section>
    );
  }

  return (
    <Section flexDirection="column" alignItems="stretch" gap={2} height="auto">
      <ContentAction
        title={t("account.title")}
        sizePreset="main-content"
        variant="section"
        padding={0}
      />
      <Card>
        <Section
          flexDirection="column"
          alignItems="start"
          gap={1}
          height="auto"
        >
          <Text font="secondary-body" color="text-02">
            {`${t("account.kind")}: ${
              isLegal
                ? t("account.kindLegalEntity")
                : t("account.kindIndividual")
            }`}
          </Text>
          <Text font="secondary-body" color="text-03">
            {`${t("account.email")}: ${data.email ?? "—"}`}
          </Text>
          {data.display_name && (
            <Text font="secondary-body" color="text-03">
              {`${t("account.name")}: ${data.display_name}`}
            </Text>
          )}
          {isLegal && data.inn && (
            <Text font="secondary-body" color="text-03">
              {`ИНН ${data.inn}${data.kpp ? ` / КПП ${data.kpp}` : ""}`}
            </Text>
          )}
        </Section>
      </Card>
      <div>
        <Button prominence="secondary" onClick={() => setEditing(true)}>
          {t("account.edit")}
        </Button>
      </div>
    </Section>
  );
}
