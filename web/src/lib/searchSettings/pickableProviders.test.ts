import { SELF_HOSTED_PROVIDERS } from "@/lib/searchSettings/constants";
import { pickableProviders } from "@/lib/searchSettings";
import { EmbeddingProviderName } from "@/lib/searchSettings/types";

function modelNames(providers: ReturnType<typeof pickableProviders>): string[] {
  return providers.flatMap((p) => p.embeddingModels.map((m) => m.modelName));
}

describe("pickableProviders", () => {
  test("hides the English-only self-hosted models", () => {
    const names = modelNames(pickableProviders(SELF_HOSTED_PROVIDERS));

    expect(names).not.toContain("nomic-ai/nomic-embed-text-v1");
    expect(names).not.toContain("intfloat/e5-base-v2");
    expect(names).not.toContain("intfloat/e5-small-v2");
  });

  test("keeps the multilingual models", () => {
    const names = modelNames(pickableProviders(SELF_HOSTED_PROVIDERS));

    expect(names).toEqual([
      "intfloat/multilingual-e5-base",
      "intfloat/multilingual-e5-small",
    ]);
  });

  test("drops a provider left without models", () => {
    const providerNames = pickableProviders(SELF_HOSTED_PROVIDERS).map(
      (p) => p.providerName
    );

    expect(providerNames).toEqual([EmbeddingProviderName.MICROSOFT]);
  });

  test("keeps a hidden model that is the current or staged one", () => {
    const names = modelNames(
      pickableProviders(SELF_HOSTED_PROVIDERS, [
        "nomic-ai/nomic-embed-text-v1",
        "intfloat/e5-small-v2",
        null,
        undefined,
      ])
    );

    expect(names).toContain("nomic-ai/nomic-embed-text-v1");
    expect(names).toContain("intfloat/e5-small-v2");
    expect(names).not.toContain("intfloat/e5-base-v2");
  });

  test("does not change the registry", () => {
    pickableProviders(SELF_HOSTED_PROVIDERS);

    expect(modelNames(SELF_HOSTED_PROVIDERS)).toContain(
      "nomic-ai/nomic-embed-text-v1"
    );
  });
});
