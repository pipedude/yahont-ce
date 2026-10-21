import { buildItems, FeatureFlags } from "@/lib/admin-sidebar-utils";
import { Permission } from "@/lib/types";

const BASE_FLAGS: FeatureFlags = {
  vectorDbEnabled: true,
  enableCloud: false,
  tier: undefined,
  customAnalyticsEnabled: false,
  hasSubscription: false,
  hooksEnabled: false,
  queryHistoryEnabled: true,
  craftAvailable: false,
};

function navIds(flags: Partial<FeatureFlags>): string[] {
  return buildItems(
    [Permission.FULL_ADMIN_PANEL_ACCESS],
    { ...BASE_FLAGS, ...flags },
    null
  ).map((item) => item.nameId);
}

describe("buildItems upgrade plan entry", () => {
  test("is hidden in Community Edition (no cloud build)", () => {
    expect(
      navIds({ enableCloud: false, hasSubscription: false })
    ).not.toContain("upgradePlan");
  });

  test("is shown in a cloud build without a subscription", () => {
    expect(navIds({ enableCloud: true, hasSubscription: false })).toContain(
      "upgradePlan"
    );
  });

  test("is hidden in a cloud build with a subscription", () => {
    expect(navIds({ enableCloud: true, hasSubscription: true })).not.toContain(
      "upgradePlan"
    );
  });
});
