"use client";

import React, { useMemo } from "react";
import { useTranslations } from "next-intl";
import { InputPasswordTypeIn, InputSingleComboBox } from "@opal/components";
import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import { ImageGenFormWrapper } from "@/views/admin/ImageGenerationPage/forms/ImageGenFormWrapper";
import {
  ImageGenFormBaseProps,
  ImageGenFormChildProps,
  ImageGenSubmitPayload,
} from "@/views/admin/ImageGenerationPage/forms/types";
import { ImageGenerationCredentials } from "@/views/admin/ImageGenerationPage/svc";
import { POLZA_URL, ROUTERAI_URL } from "@/lib/languageModels/gatewayLinks";
import { LLMProviderView } from "@/lib/languageModels/types";

/** Russian image gateways that take the tenant's own API key. */
const GATEWAYS: Record<string, { name: string; url: string }> = {
  routerai: { name: "RouterAI", url: ROUTERAI_URL },
  polza: { name: "Polza.AI", url: POLZA_URL },
};

// api_base stays hidden. It carries the stored base through edits and clone
// mode: with a stored key the backend requires the same api_base (MT mode).
interface GatewayFormValues {
  api_key: string;
  api_base: string;
}

const initialValues: GatewayFormValues = {
  api_key: "",
  api_base: "",
};

const EXISTING_PREFIX = "existing:";

function GatewayFormFields(props: ImageGenFormChildProps<GatewayFormValues>) {
  const t = useTranslations("admin.imageGeneration");
  const {
    apiStatus,
    showApiMessage,
    errorMessage,
    disabled,
    isLoadingCredentials,
    apiKeyOptions,
    resetApiState,
    imageProvider,
  } = props;
  const gateway = GATEWAYS[imageProvider.provider_name];

  return (
    <FormikField<string>
      name="api_key"
      render={(field, helper, meta, state) => (
        <FormField
          name="api_key"
          state={apiStatus === "error" ? "error" : state}
          className="w-full"
        >
          <FormField.Label>{t("form.apiKey.label")}</FormField.Label>
          <FormField.Control>
            {apiKeyOptions.length > 0 ? (
              <InputSingleComboBox
                mode="open"
                value={field.value}
                onChange={(e) => {
                  helper.setValue(e.target.value);
                  resetApiState();
                }}
                onValueChange={(value) => {
                  helper.setValue(value);
                  resetApiState();
                }}
                onBlur={field.onBlur}
                options={apiKeyOptions}
                placeholder={
                  isLoadingCredentials
                    ? t("form.loading.placeholder")
                    : t("form.apiKey.comboPlaceholder")
                }
                disabled={disabled}
                isError={apiStatus === "error"}
              />
            ) : (
              <InputPasswordTypeIn
                {...field}
                onChange={(e) => {
                  field.onChange(e);
                  resetApiState();
                }}
                placeholder={
                  isLoadingCredentials
                    ? t("form.loading.placeholder")
                    : t("form.apiKey.placeholder")
                }
                disabled={disabled}
                error={apiStatus === "error"}
              />
            )}
          </FormField.Control>
          {showApiMessage ? (
            <FormField.APIMessage
              state={apiStatus}
              messages={{
                loading: t("form.apiKeyTest.loading", {
                  title: imageProvider.title,
                }),
                success: t("form.apiKeyTest.success"),
                error: errorMessage || t("form.apiKeyTest.error"),
              }}
            />
          ) : (
            <FormField.Message
              messages={{
                idle: t.rich("form.gatewayApiKey.idle", {
                  gateway: gateway?.name ?? imageProvider.provider_name,
                  link: (chunks) => (
                    <a
                      href={gateway?.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline"
                    >
                      {chunks}
                    </a>
                  ),
                }),
                error: meta.error,
              }}
            />
          )}
        </FormField>
      )}
    />
  );
}

function getInitialValuesFromCredentials(
  credentials: ImageGenerationCredentials
): Partial<GatewayFormValues> {
  return {
    api_key: credentials.api_key || "",
    api_base: credentials.api_base || "",
  };
}

function resolveApiBase(
  values: GatewayFormValues,
  existingProviders: LLMProviderView[]
): string | undefined {
  // Clone mode reuses a connected RouterAI / Polza LLM provider: its api_base
  // must be sent unchanged.
  if (values.api_key.startsWith(EXISTING_PREFIX)) {
    const sourceId = Number(values.api_key.split(":")[1]);
    const source = existingProviders.find((p) => p.id === sourceId);
    return source?.api_base || undefined;
  }
  return values.api_base || undefined;
}

export function GatewayImageGenForm(props: ImageGenFormBaseProps) {
  const t = useTranslations("admin.imageGeneration");
  const { imageProvider, existingConfig, existingProviders } = props;

  const validationSchema = useMemo(
    () =>
      Yup.object().shape({
        api_key: Yup.string().required(t("form.apiKey.required")),
      }),
    [t]
  );

  function transformValues(values: GatewayFormValues): ImageGenSubmitPayload {
    return {
      modelName: imageProvider.model_name,
      imageProviderId: imageProvider.image_provider_id,
      provider: imageProvider.provider_name,
      apiKey: values.api_key,
      apiBase: resolveApiBase(values, existingProviders),
    };
  }

  return (
    <ImageGenFormWrapper<GatewayFormValues>
      {...props}
      title={
        existingConfig
          ? t("form.editHeader.title", { title: imageProvider.title })
          : t("form.connectHeader.title", { title: imageProvider.title })
      }
      description={t(imageProvider.descriptionKey)}
      initialValues={initialValues}
      validationSchema={validationSchema}
      getInitialValuesFromCredentials={getInitialValuesFromCredentials}
      transformValues={transformValues}
    >
      {(childProps) => <GatewayFormFields {...childProps} />}
    </ImageGenFormWrapper>
  );
}
