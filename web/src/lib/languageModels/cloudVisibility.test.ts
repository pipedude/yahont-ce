/**
 * Cloud-only provider visibility. The Yahont cloud is hosted in Russia,
 * and OpenAI, Anthropic, Google, AWS and Microsoft do not serve it — their
 * cards in "Add provider" are hidden there. On-premise builds keep them.
 */

import {
  isProviderHiddenInCloud,
  isVoiceProviderHiddenInCloud,
  isWebSearchProviderHiddenInCloud,
  isConnectorSourceHidden,
  isEmbeddingModelHidden,
} from "@/lib/languageModels/cloudVisibility";
import { LLMProviderName } from "@/lib/languageModels/types";

const RUSSIA_UNAVAILABLE = [
  LLMProviderName.OPENAI,
  LLMProviderName.ANTHROPIC,
  LLMProviderName.VERTEX_AI,
  LLMProviderName.BEDROCK,
  LLMProviderName.AZURE,
];

const ALWAYS_AVAILABLE = [
  LLMProviderName.ROUTERAI,
  LLMProviderName.POLZA,
  LLMProviderName.OPENROUTER,
  LLMProviderName.LITELLM_PROXY,
  LLMProviderName.PORTKEY,
  LLMProviderName.VERCEL_AI_GATEWAY,
  LLMProviderName.NEBIUS_TOKENFACTORY,
  LLMProviderName.BIFROST,
  LLMProviderName.OLLAMA_CHAT,
  LLMProviderName.LM_STUDIO,
  LLMProviderName.OPENAI_COMPATIBLE,
  LLMProviderName.YAHONT,
  "custom",
];

describe("isProviderHiddenInCloud", () => {
  test.each(RUSSIA_UNAVAILABLE)("hides %s in the cloud build", (name) => {
    expect(isProviderHiddenInCloud(name, true)).toBe(true);
  });

  test.each(RUSSIA_UNAVAILABLE)("keeps %s in on-premise builds", (name) => {
    expect(isProviderHiddenInCloud(name, false)).toBe(false);
  });

  test.each(ALWAYS_AVAILABLE)("keeps %s in the cloud build", (name) => {
    expect(isProviderHiddenInCloud(name, true)).toBe(false);
  });
});

describe("isVoiceProviderHiddenInCloud", () => {
  test.each(["openai", "azure", "elevenlabs"])(
    "hides %s only in the cloud build",
    (type) => {
      expect(isVoiceProviderHiddenInCloud(type, true)).toBe(true);
      expect(isVoiceProviderHiddenInCloud(type, false)).toBe(false);
    }
  );

  test.each(["zoom", "routerai", "polza"])(
    "keeps %s in the cloud build",
    (type) => {
      expect(isVoiceProviderHiddenInCloud(type, true)).toBe(false);
    }
  );
});

// Probed from the Moscow server 2026-10-10: Exa answers with a Cloudflare 403
// page; the others reach their key check. Google PSE is closed to new
// customers.
describe("isWebSearchProviderHiddenInCloud", () => {
  test.each(["exa", "google_pse"])(
    "hides %s only in the cloud build",
    (type) => {
      expect(isWebSearchProviderHiddenInCloud(type, true)).toBe(true);
      expect(isWebSearchProviderHiddenInCloud(type, false)).toBe(false);
    }
  );

  test.each([
    "srezai",
    "serper",
    "brave",
    "searxng",
    "tavily",
    "firecrawl",
    "onyx_web_crawler",
  ])("keeps %s in the cloud build", (type) => {
    expect(isWebSearchProviderHiddenInCloud(type, true)).toBe(false);
  });
});

describe("isConnectorSourceHidden", () => {
  test.each([
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
  ])("hides %s in every build", (source) => {
    expect(isConnectorSourceHidden(source)).toBe(true);
  });

  // Confluence and Jira also serve self-hosted Server/Data Center.
  test.each([
    "confluence",
    "jira",
    "notion",
    "outlook",
    "sharepoint",
    "onedrive",
    "slack",
    "bitbucket",
    "teams",
    "google_drive",
    "github",
    "gitlab",
    "web",
    "file",
  ])("keeps %s in the catalog", (source) => {
    expect(isConnectorSourceHidden(source)).toBe(false);
  });
});

describe("isEmbeddingModelHidden", () => {
  test.each([
    "nomic-ai/nomic-embed-text-v1",
    "intfloat/e5-base-v2",
    "intfloat/e5-small-v2",
  ])("hides the English-only model %s", (modelName) => {
    expect(isEmbeddingModelHidden(modelName)).toBe(true);
  });

  test.each([
    "intfloat/multilingual-e5-small",
    "intfloat/multilingual-e5-base",
    "text-embedding-3-large",
    "cohere/embed-v4.0",
    "my-org/custom-model",
  ])("keeps %s", (modelName) => {
    expect(isEmbeddingModelHidden(modelName)).toBe(false);
  });
});
