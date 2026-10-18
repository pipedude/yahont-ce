"use client";

import { useTranslations } from "next-intl";
import { markdown } from "@opal/utils";
import {
  LLMProviderFormProps,
  LLMProviderName,
} from "@/lib/languageModels/types";
import { fetchRouterAIModels } from "@/lib/languageModels/svc";
import { ROUTERAI_URL } from "@/lib/languageModels/gatewayLinks";
import GatewayModal from "@/sections/modals/languageModels/GatewayModal";

const DEFAULT_API_BASE = "https://routerai.ru/api/v1";

export default function RouterAIModal(props: LLMProviderFormProps) {
  const t = useTranslations("admin.languageModels.modals");

  return (
    <GatewayModal
      {...props}
      providerName={LLMProviderName.ROUTERAI}
      defaultApiBase={DEFAULT_API_BASE}
      fetchModels={fetchRouterAIModels}
      apiBaseDescription={t("routerAi.apiBaseField.description")}
      apiKeyDescription={markdown(
        t("routerAi.apiKeyField.description", { url: ROUTERAI_URL })
      )}
    />
  );
}
