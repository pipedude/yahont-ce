import { ADMIN_ROUTES, FeatureFlags } from "./admin-routes";

function flags(overrides: Partial<FeatureFlags> = {}): FeatureFlags {
  return {
    vectorDbEnabled: true,
    enableCloud: false,
    tier: undefined,
    customAnalyticsEnabled: false,
    hasSubscription: true,
    hooksEnabled: false,
    queryHistoryEnabled: true,
    craftAvailable: false,
    ...overrides,
  };
}

describe("ADMIN_ROUTES.INDEX_SETTINGS", () => {
  // The page used to be hidden in cloud (`!f.enableCloud`), leaving
  // cloud tenants with no way to pick a captioning model for image
  // extraction. The route itself already handles the cloud split (embedding
  // model, quantization, multipass/contextual stay locked via CloudDisabled
  // inside the page) — only Image Processing needs to be reachable.
  it("is visible in cloud when the vector DB is enabled", () => {
    expect(
      ADMIN_ROUTES.INDEX_SETTINGS.visibleWhen?.(
        flags({ enableCloud: true, vectorDbEnabled: true })
      )
    ).toBe(true);
  });

  it("is visible self-hosted when the vector DB is enabled", () => {
    expect(
      ADMIN_ROUTES.INDEX_SETTINGS.visibleWhen?.(
        flags({ enableCloud: false, vectorDbEnabled: true })
      )
    ).toBe(true);
  });

  it("stays hidden without a vector DB, cloud or not", () => {
    expect(
      ADMIN_ROUTES.INDEX_SETTINGS.visibleWhen?.(
        flags({ enableCloud: true, vectorDbEnabled: false })
      )
    ).toBe(false);
    expect(
      ADMIN_ROUTES.INDEX_SETTINGS.visibleWhen?.(
        flags({ enableCloud: false, vectorDbEnabled: false })
      )
    ).toBe(false);
  });
});

describe("ADMIN_ROUTES.DISCORD_BOTS", () => {
  // The cloud has no platform bot token, and Discord is blocked for users in
  // Russia; self-hosted admins bring their own bot.
  it("is hidden in the cloud", () => {
    expect(
      ADMIN_ROUTES.DISCORD_BOTS.visibleWhen?.(flags({ enableCloud: true }))
    ).toBe(false);
  });

  it("is visible self-hosted", () => {
    expect(
      ADMIN_ROUTES.DISCORD_BOTS.visibleWhen?.(flags({ enableCloud: false }))
    ).toBe(true);
  });
});
