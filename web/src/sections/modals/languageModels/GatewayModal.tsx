"use client";

import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { InputDivider, toast } from "@opal/layouts";
import type { RichStr } from "@opal/types";
import {
  GatewayFetchParams,
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
  ModelConfiguration,
} from "@/lib/languageModels/types";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
  withFetchedModels,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import {
  APIKeyField,
  APIBaseField,
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/languageModels/shared";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";

type FetchGatewayModels = (
  params: GatewayFetchParams
) => Promise<{ models: ModelConfiguration[]; error?: string }>;

interface GatewayConnection {
  providerName: LLMProviderName;
  defaultApiBase: string;
  fetchModels: FetchGatewayModels;
  apiBaseDescription: string;
  apiKeyDescription: RichStr;
}

interface GatewayModalInternalsProps extends GatewayConnection {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function GatewayModalInternals({
  existingLlmProvider,
  isOnboarding,
  defaultApiBase,
  fetchModels,
  apiBaseDescription,
  apiKeyDescription,
}: GatewayModalInternalsProps) {
  const formikProps = useFormikContext<BaseLLMFormValues>();

  const isFetchDisabled = !formikProps.values.api_base;

  const handleFetchModels = async () => {
    const { models, error } = await fetchModels({
      api_base: formikProps.values.api_base,
      api_key: formikProps.values.api_key || undefined,
      provider_id: existingLlmProvider?.id ?? undefined,
    });
    if (error) {
      throw new Error(error);
    }
    formikProps.setValues(withFetchedModels(models));
  };

  return (
    <>
      <APIBaseField
        subDescription={apiBaseDescription}
        placeholder={defaultApiBase}
      />

      <APIKeyField subDescription={apiKeyDescription} />

      {!isOnboarding && (
        <>
          <InputDivider />
          <DisplayNameField />
        </>
      )}

      <InputDivider />
      <ModelSelectionField
        shouldShowAutoUpdateToggle={false}
        onRefetch={isFetchDisabled ? undefined : handleFetchModels}
      />

      {!isOnboarding && (
        <>
          <InputDivider />
          <ModelAccessField />
        </>
      )}
    </>
  );
}

export interface GatewayModalProps
  extends LLMProviderFormProps, GatewayConnection {}

/** Connection form shared by the OpenAI-compatible gateways (RouterAI, Polza.ai). */
export default function GatewayModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onSuccess,
  analyticsSource,
  providerName,
  defaultApiBase,
  fetchModels,
  apiBaseDescription,
  apiKeyDescription,
}: GatewayModalProps) {
  const t = useTranslations("admin.languageModels.modals");
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues: BaseLLMFormValues = {
    ...useInitialValues(isOnboarding, providerName, existingLlmProvider),
    api_base: existingLlmProvider?.api_base ?? defaultApiBase,
  };

  const validationSchema = buildValidationSchema(t, isOnboarding, {
    apiKey: true,
    apiBase: true,
  });

  return (
    <ModalWrapper
      providerName={providerName}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        await submitProvider({
          t,
          analyticsSource:
            analyticsSource ??
            (isOnboarding
              ? LLMProviderConfiguredSource.CHAT_ONBOARDING
              : LLMProviderConfiguredSource.ADMIN_PAGE),
          providerName,
          values,
          initialValues,
          existingLlmProvider,
          shouldMarkAsDefault,
          setStatus,
          setSubmitting,
          onClose,
          onSuccess: async () => {
            if (onSuccess) {
              await onSuccess();
            } else {
              await refreshLlmProviderCaches(mutate);
              toast.success(
                existingLlmProvider
                  ? t("toasts.providerUpdated")
                  : t("toasts.providerEnabled")
              );
            }
          },
        });
      }}
    >
      <GatewayModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
        providerName={providerName}
        defaultApiBase={defaultApiBase}
        fetchModels={fetchModels}
        apiBaseDescription={apiBaseDescription}
        apiKeyDescription={apiKeyDescription}
      />
    </ModalWrapper>
  );
}
