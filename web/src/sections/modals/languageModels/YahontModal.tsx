"use client";

import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { InputDivider, toast } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
} from "@/lib/languageModels/types";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import {
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/languageModels/shared";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";

/**
 * Settings for the platform-managed Yahont provider. An admin can rename it,
 * choose which of its models are visible, tune per-model settings and set who
 * has access. The connection and the model list come from the platform and the
 * server rejects any other change, so the form shows none of those fields.
 */
export default function YahontModal({
  existingLlmProvider,
  onOpenChange,
  onSuccess,
  analyticsSource,
}: LLMProviderFormProps) {
  const t = useTranslations("admin.languageModels.modals");
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues: BaseLLMFormValues = useInitialValues(
    false,
    LLMProviderName.YAHONT,
    existingLlmProvider
  );

  const validationSchema = buildValidationSchema(t, false);

  return (
    <ModalWrapper
      providerName={LLMProviderName.YAHONT}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      description={t("yahont.description")}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        await submitProvider({
          t,
          analyticsSource:
            analyticsSource ?? LLMProviderConfiguredSource.ADMIN_PAGE,
          providerName: LLMProviderName.YAHONT,
          values,
          initialValues,
          existingLlmProvider,
          setStatus,
          setSubmitting,
          onClose,
          onSuccess: async () => {
            if (onSuccess) {
              await onSuccess();
            } else {
              await refreshLlmProviderCaches(mutate);
              toast.success(t("toasts.providerUpdated"));
            }
          },
        });
      }}
    >
      <DisplayNameField />
      <InputDivider />
      <ModelSelectionField shouldShowAutoUpdateToggle={false} />
      <InputDivider />
      <ModelAccessField />
    </ModalWrapper>
  );
}
