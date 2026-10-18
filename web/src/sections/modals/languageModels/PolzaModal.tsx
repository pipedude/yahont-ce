"use client";

import { useTranslations } from "next-intl";
import { markdown } from "@opal/utils";
import {
  LLMProviderFormProps,
  LLMProviderName,
} from "@/lib/languageModels/types";
import { fetchPolzaModels } from "@/lib/languageModels/svc";
import { POLZA_URL } from "@/lib/languageModels/gatewayLinks";
import GatewayModal from "@/sections/modals/languageModels/GatewayModal";

const DEFAULT_API_BASE = "https://polza.ai/api/v1";

export default function PolzaModal(props: LLMProviderFormProps) {
  const t = useTranslations("admin.languageModels.modals");

  return (
    <GatewayModal
      {...props}
      providerName={LLMProviderName.POLZA}
      defaultApiBase={DEFAULT_API_BASE}
      fetchModels={fetchPolzaModels}
      apiBaseDescription={t("polza.apiBaseField.description")}
      apiKeyDescription={markdown(
        t("polza.apiKeyField.description", { url: POLZA_URL })
      )}
    />
  );
}
