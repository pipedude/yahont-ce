import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { isProviderHiddenInCloud } from "@/lib/languageModels/cloudVisibility";

/**
 * Message key of a provider blurb, inside the `admin.imageGeneration`
 * namespace. Held as a key (not copy) so the catalog stays the single source
 * of the English text while the registry stays a plain module.
 */
export type ImageProviderDescriptionKey =
  | "providers.openaiGptImage25Flare.description"
  | "providers.openaiGptImage25Sunburst.description"
  | "providers.openaiGptImage2.description"
  | "providers.openaiGptImage15.description"
  | "providers.openaiGptImage1.description"
  | "providers.azureGptImage25Flare.description"
  | "providers.azureGptImage25Sunburst.description"
  | "providers.azureGptImage2.description"
  | "providers.azureGptImage15.description"
  | "providers.azureGptImage1.description"
  | "providers.gemini25FlashImage.description"
  | "providers.gemini3ProImage.description"
  | "providers.gemini3ProImagePreview.description"
  | "providers.geminiNanoBanana21.description"
  | "providers.gemini31FlashImage.description";

/** Message key of a vendor group title; takes the vendor `name`. */
export type ImageProviderGroupTitleKey = "providerGroups.worksInRussia.title";

export interface ImageProvider {
  image_provider_id: string; // Static unique key for UI-DB mapping
  model_name: string; // Actual model name for LLM API
  provider_name: string;
  title: string;
  descriptionKey: ImageProviderDescriptionKey;
  deprecated?: boolean; // Hidden unless already connected (model no longer offered upstream)
}

export interface ProviderGroup {
  // Vendor name — a proper noun, so it is not translated.
  name: string;
  titleKey?: ImageProviderGroupTitleKey;
  providers: ImageProvider[];
}

// Russian gateways (Yahont fork): the tenant's own key, no platform billing.
// Model ids keep the vendor prefix — both gateways route on it.
function gatewayProviders(gateway: "routerai" | "polza"): ImageProvider[] {
  return [
    {
      image_provider_id: `${gateway}_gpt_image_2_5_sunburst`,
      model_name: "openai/gpt-image-2.5-sunburst",
      provider_name: gateway,
      title: "GPT Image 2.5 Sunburst",
      descriptionKey: "providers.openaiGptImage25Sunburst.description",
    },
    {
      image_provider_id: `${gateway}_gpt_image_2_5_flare`,
      model_name: "openai/gpt-image-2.5-flare",
      provider_name: gateway,
      title: "GPT Image 2.5 Flare",
      descriptionKey: "providers.openaiGptImage25Flare.description",
    },
    // Withdrawn 2026-10-09: the Google safety filter refused even neutral
    // prompts through the gateways. Listed only while still connected.
    {
      image_provider_id: `${gateway}_gemini_nano_banana_2_1`,
      model_name: "google/gemini-nano-banana-2.1",
      provider_name: gateway,
      title: "Nano Banana 2.1",
      descriptionKey: "providers.geminiNanoBanana21.description",
      deprecated: true,
    },
    {
      image_provider_id: `${gateway}_gemini_3_1_flash_image`,
      model_name: "google/gemini-3.1-flash-image",
      provider_name: gateway,
      title: "Nano Banana 2 (Gemini 3.1 Flash Image)",
      descriptionKey: "providers.gemini31FlashImage.description",
      deprecated: true,
    },
  ];
}

export const IMAGE_PROVIDER_GROUPS: ProviderGroup[] = [
  {
    name: "RouterAI",
    titleKey: "providerGroups.worksInRussia.title",
    providers: gatewayProviders("routerai"),
  },
  {
    name: "Polza.AI",
    titleKey: "providerGroups.worksInRussia.title",
    providers: gatewayProviders("polza"),
  },
  {
    name: "OpenAI",
    providers: [
      {
        image_provider_id: "openai_gpt_image_2_5_flare",
        model_name: "gpt-image-2.5-flare",
        provider_name: "openai",
        title: "GPT Image 2.5 Flare",
        descriptionKey: "providers.openaiGptImage25Flare.description",
      },
      {
        image_provider_id: "openai_gpt_image_2_5_sunburst",
        model_name: "gpt-image-2.5-sunburst",
        provider_name: "openai",
        title: "GPT Image 2.5 Sunburst",
        descriptionKey: "providers.openaiGptImage25Sunburst.description",
      },
      {
        image_provider_id: "openai_gpt_image_2",
        model_name: "gpt-image-2",
        provider_name: "openai",
        title: "GPT Image 2",
        descriptionKey: "providers.openaiGptImage2.description",
      },
      {
        image_provider_id: "openai_gpt_image_1_5",
        model_name: "gpt-image-1.5",
        provider_name: "openai",
        title: "GPT Image 1.5",
        descriptionKey: "providers.openaiGptImage15.description",
      },
      {
        image_provider_id: "openai_gpt_image_1",
        model_name: "gpt-image-1",
        provider_name: "openai",
        title: "GPT Image 1",
        descriptionKey: "providers.openaiGptImage1.description",
        deprecated: true,
      },
    ],
  },
  {
    name: "Azure OpenAI",
    providers: [
      {
        image_provider_id: "azure_gpt_image_2_5_flare",
        model_name: "", // Extracted from deployment in target URI
        provider_name: "azure",
        title: "Azure OpenAI GPT Image 2.5 Flare",
        descriptionKey: "providers.azureGptImage25Flare.description",
      },
      {
        image_provider_id: "azure_gpt_image_2_5_sunburst",
        model_name: "", // Extracted from deployment in target URI
        provider_name: "azure",
        title: "Azure OpenAI GPT Image 2.5 Sunburst",
        descriptionKey: "providers.azureGptImage25Sunburst.description",
      },
      {
        image_provider_id: "azure_gpt_image_2",
        model_name: "", // Extracted from deployment in target URI
        provider_name: "azure",
        title: "Azure OpenAI GPT Image 2",
        descriptionKey: "providers.azureGptImage2.description",
      },
      {
        image_provider_id: "azure_gpt_image_1_5",
        model_name: "", // Extracted from deployment in target URI
        provider_name: "azure",
        title: "Azure OpenAI GPT Image 1.5",
        descriptionKey: "providers.azureGptImage15.description",
      },
      {
        image_provider_id: "azure_gpt_image_1",
        model_name: "", // Extracted from deployment in target URI
        provider_name: "azure",
        title: "Azure OpenAI GPT Image 1",
        descriptionKey: "providers.azureGptImage1.description",
      },
    ],
  },
  {
    name: "Google Cloud Vertex AI",
    providers: [
      {
        image_provider_id: "gemini-2.5-flash-image",
        model_name: "gemini-2.5-flash-image",
        provider_name: "vertex_ai",
        title: "Gemini 2.5 Flash Image",
        descriptionKey: "providers.gemini25FlashImage.description",
      },
      {
        image_provider_id: "gemini-3-pro-image",
        model_name: "gemini-3-pro-image",
        provider_name: "vertex_ai",
        title: "Gemini 3 Pro Image",
        descriptionKey: "providers.gemini3ProImage.description",
      },
      {
        image_provider_id: "gemini-3-pro-image-preview",
        model_name: "gemini-3-pro-image-preview",
        provider_name: "vertex_ai",
        title: "Gemini 3 Pro Image Preview",
        descriptionKey: "providers.gemini3ProImagePreview.description",
        deprecated: true,
      },
    ],
  },
];

/**
 * Whether a model card is listed. Deprecated models, and vendors not offered
 * in the cloud build, stay listed only once connected, so the admin can
 * still disconnect or switch away.
 */
export function isImageProviderListed(
  provider: ImageProvider,
  isConnected: boolean,
  cloudEnabled: boolean = NEXT_PUBLIC_CLOUD_ENABLED
): boolean {
  return (
    isConnected ||
    (!provider.deprecated &&
      !isProviderHiddenInCloud(provider.provider_name, cloudEnabled))
  );
}
