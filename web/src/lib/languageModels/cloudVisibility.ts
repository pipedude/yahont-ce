import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { LLMProviderName } from "@/lib/languageModels/types";

// Not offered in the cloud build: the Yahont cloud is hosted in Russia,
// and OpenAI, Anthropic, Google, AWS and Microsoft do not serve it.
const CLOUD_HIDDEN_PROVIDERS: ReadonlySet<string> = new Set([
  LLMProviderName.OPENAI,
  LLMProviderName.ANTHROPIC,
  LLMProviderName.VERTEX_AI,
  LLMProviderName.BEDROCK,
  LLMProviderName.AZURE,
]);

export function isProviderHiddenInCloud(
  providerName: string,
  cloudEnabled: boolean = NEXT_PUBLIC_CLOUD_ENABLED
): boolean {
  return cloudEnabled && CLOUD_HIDDEN_PROVIDERS.has(providerName);
}

// Voice provider types not offered in the cloud build. Zoom serves Russia.
const CLOUD_HIDDEN_VOICE_PROVIDERS: ReadonlySet<string> = new Set([
  "openai",
  "azure",
  "elevenlabs",
]);

export function isVoiceProviderHiddenInCloud(
  providerType: string,
  cloudEnabled: boolean = NEXT_PUBLIC_CLOUD_ENABLED
): boolean {
  return cloudEnabled && CLOUD_HIDDEN_VOICE_PROVIDERS.has(providerType);
}

// Web search providers not offered in the cloud build: Exa blocks Russia at
// its Cloudflare edge, and Google's Custom Search JSON API is closed to new
// customers.
const CLOUD_HIDDEN_WEB_SEARCH_PROVIDERS: ReadonlySet<string> = new Set([
  "exa",
  "google_pse",
]);

export function isWebSearchProviderHiddenInCloud(
  providerType: string,
  cloudEnabled: boolean = NEXT_PUBLIC_CLOUD_ENABLED
): boolean {
  return cloudEnabled && CLOUD_HIDDEN_WEB_SEARCH_PROVIDERS.has(providerType);
}

// Connector sources not offered in the Add Connector catalog, in the cloud and
// in Community Edition alike (probed from the Moscow
// server 2026-10-10, plus published sanctions notices). Linear, Document360
// and Gong refuse Russian IPs; HubSpot, ClickUp, Asana, Airtable, Salesforce
// and Zendesk disable accounts of Russian companies. The rest of the list
// (Axero to Canvas) work from Russia but have no market there; the owner
// hid them on 2026-10-18. Notion, Slack, Bitbucket, SharePoint, OneDrive,
// Teams and Outlook are shown again by the owner's decision of the same day.
// Confluence and Jira stay: they also connect to self-hosted Server/Data
// Center. YouTrack is hidden by the owner's decision of 2026-10-23: JetBrains
// does not serve YouTrack Cloud in Russia; the Server edition goes with it.
const HIDDEN_CONNECTOR_SOURCES: ReadonlySet<string> = new Set([
  "linear",
  "document360",
  "gong",
  "hubspot",
  "clickup",
  "asana",
  "airtable",
  "salesforce",
  "zendesk",
  "axero",
  "guru",
  "loopio",
  "lumapps",
  "slab",
  "drupal_wiki",
  "egnyte",
  "box",
  "oci_storage",
  "r2",
  "coda",
  "productboard",
  "fireflies",
  "highspot",
  "canvas",
  "youtrack",
]);

export function isConnectorSourceHidden(source: string): boolean {
  return HIDDEN_CONNECTOR_SOURCES.has(source);
}

// Decision Models (upstream beta) are hidden in the cloud and in Community
// Edition alike, by the owner's decision of 2026-11-08: no feature uses the
// selected model yet. The page, its sidebar entry and the Decision tag on
// model rows go; the decision-only providers (TypeSafe AI, Zoom AI) appear
// only on that page.
export const DECISION_MODELS_HIDDEN = true;
