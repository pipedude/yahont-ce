/**
 * Model fetching for the OpenAI-compatible gateways RouterAI and Polza.ai.
 */

import {
  fetchModels,
  fetchPolzaModels,
  fetchRouterAIModels,
} from "@/lib/languageModels/svc";
import { LLMProviderName } from "@/lib/languageModels/types";

const CATALOG = [
  {
    name: "deepseek/deepseek-v4-pro",
    display_name: "DeepSeek V4 Pro",
    max_input_tokens: 1000000,
    supports_image_input: false,
    supports_reasoning: true,
  },
  {
    name: "anthropic/claude-sonnet-4.5",
    display_name: "Claude Sonnet 4.5",
    max_input_tokens: null,
    supports_image_input: true,
    supports_reasoning: false,
  },
];

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("gateway model fetching", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  test.each([
    ["RouterAI", fetchRouterAIModels, "routerai"],
    ["Polza.ai", fetchPolzaModels, "polza"],
  ])(
    "%s posts to its own endpoint with the form values",
    async (_, fn, slug) => {
      fetchSpy.mockResolvedValue(jsonResponse(CATALOG));

      await fn({
        api_base: "https://gw.example/v1",
        api_key: "k",
        provider_id: 3,
      });

      const [url, init] = fetchSpy.mock.calls[0];
      expect(url).toBe(`/api/admin/llm/${slug}/available-models`);
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body)).toEqual({
        api_base: "https://gw.example/v1",
        api_key: "k",
        provider_id: 3,
      });
    }
  );

  test("maps the catalog to visible model configurations", async () => {
    fetchSpy.mockResolvedValue(jsonResponse(CATALOG));

    const { models, error } = await fetchRouterAIModels({});

    expect(error).toBeUndefined();
    expect(models).toEqual([
      expect.objectContaining({
        name: "deepseek/deepseek-v4-pro",
        is_visible: true,
        max_input_tokens: 1000000,
        supports_reasoning: true,
        effectiveDisplayName: "DeepSeek V4 Pro",
      }),
      expect.objectContaining({
        name: "anthropic/claude-sonnet-4.5",
        is_visible: true,
        max_input_tokens: null,
        supports_image_input: true,
        effectiveDisplayName: "Claude Sonnet 4.5",
      }),
    ]);
  });

  test("returns the server's error detail when the request fails", async () => {
    fetchSpy.mockResolvedValue(
      jsonResponse({ detail: "Authentication failed" }, 400)
    );

    const result = await fetchPolzaModels({});

    expect(result).toEqual({ models: [], error: "Authentication failed" });
  });

  test("returns the network error message when the request throws", async () => {
    fetchSpy.mockRejectedValue(new Error("offline"));

    const result = await fetchRouterAIModels({});

    expect(result).toEqual({ models: [], error: "offline" });
  });

  test.each([
    [LLMProviderName.ROUTERAI, "routerai"],
    [LLMProviderName.POLZA, "polza"],
  ])("fetchModels dispatches %s to its endpoint", async (provider, slug) => {
    fetchSpy.mockResolvedValue(jsonResponse(CATALOG));

    await fetchModels(provider, { api_base: "https://gw.example/v1", id: 5 });

    expect(fetchSpy.mock.calls[0][0]).toBe(
      `/api/admin/llm/${slug}/available-models`
    );
    expect(JSON.parse(fetchSpy.mock.calls[0][1].body).provider_id).toBe(5);
  });
});
