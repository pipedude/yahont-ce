/**
 * Image generation cards in the cloud build: only the Russian
 * gateways (RouterAI, Polza.AI) are offered; OpenAI, Azure and Vertex AI stay
 * listed only once connected. On-premise builds keep every vendor.
 */

import {
  IMAGE_PROVIDER_GROUPS,
  ImageProvider,
  isImageProviderListed,
} from "@/views/admin/ImageGenerationPage/constants";

const ALL_PROVIDERS: ImageProvider[] = IMAGE_PROVIDER_GROUPS.flatMap(
  (group) => group.providers
);

function listedProviderNames(cloudEnabled: boolean): Set<string> {
  return new Set(
    ALL_PROVIDERS.filter((p) =>
      isImageProviderListed(p, false, cloudEnabled)
    ).map((p) => p.provider_name)
  );
}

describe("isImageProviderListed", () => {
  test("the cloud build lists only the Russian gateways", () => {
    expect(listedProviderNames(true)).toEqual(new Set(["routerai", "polza"]));
  });

  test("on-premise builds list every vendor", () => {
    expect(listedProviderNames(false)).toEqual(
      new Set(["routerai", "polza", "openai", "azure", "vertex_ai"])
    );
  });

  test("a connected hidden vendor stays listed in the cloud", () => {
    const openai = ALL_PROVIDERS.find((p) => p.provider_name === "openai");
    expect(openai).toBeDefined();
    expect(isImageProviderListed(openai!, true, true)).toBe(true);
  });

  test("a deprecated model is listed only once connected", () => {
    const deprecated = ALL_PROVIDERS.find((p) => p.deprecated);
    expect(deprecated).toBeDefined();
    expect(isImageProviderListed(deprecated!, false, false)).toBe(false);
    expect(isImageProviderListed(deprecated!, true, false)).toBe(true);
  });
});

describe("Russian gateway groups", () => {
  test.each(["RouterAI", "Polza.AI"])(
    "%s offers the agreed models with the vendor prefix",
    (name) => {
      const group = IMAGE_PROVIDER_GROUPS.find((g) => g.name === name);
      expect(group?.titleKey).toBe("providerGroups.worksInRussia.title");
      const offered = (group?.providers ?? []).filter((p) =>
        isImageProviderListed(p, false, true)
      );
      expect(offered.map((p) => p.model_name)).toEqual([
        "openai/gpt-image-2.5-sunburst",
        "openai/gpt-image-2.5-flare",
      ]);
    }
  );

  test("withdrawn Gemini models stay listed only while connected", () => {
    const gemini = ALL_PROVIDERS.filter(
      (p) =>
        (p.provider_name === "routerai" || p.provider_name === "polza") &&
        p.model_name.startsWith("google/")
    );
    expect(gemini).toHaveLength(4);
    for (const provider of gemini) {
      expect(isImageProviderListed(provider, false, true)).toBe(false);
      expect(isImageProviderListed(provider, true, true)).toBe(true);
    }
  });

  test("image provider ids are unique", () => {
    const ids = ALL_PROVIDERS.map((p) => p.image_provider_id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
