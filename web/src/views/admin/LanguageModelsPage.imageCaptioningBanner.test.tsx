/**
 * The "no captioning model chosen" banner on the Language Models page.
 * Upstream #14965 removed the fallback vision-model pick: with no
 * default set, image extraction silently stops producing any text, and the
 * cloud Index Settings page where an admin would fix this was hidden from
 * the sidebar. The banner is the signal that survives that: it is shown
 * everywhere (cloud and self-hosted), not gated on whether the tenant even
 * has a vision-capable model, so an admin with none still learns something
 * is wrong.
 */

import { render, screen } from "@tests/setup/test-utils";
import LanguageModelsPage from "@/views/admin/LanguageModelsPage";
import type { DefaultModel } from "@/lib/languageModels/types";

const mockMutate = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => "/admin/language-models",
}));

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  useSWRConfig: () => ({ mutate: mockMutate }),
}));

jest.mock("@/lib/languageModels/costOverrides", () => ({
  useCostOverrides: () => ({
    costOverrides: [],
    isLoading: false,
    error: undefined,
  }),
  deleteCostOverride: jest.fn(),
  refreshCostOverrides: jest.fn(),
  upsertCostOverride: jest.fn(),
}));

jest.mock("@/lib/analytics/hooks", () => ({
  ...jest.requireActual("@/lib/analytics/hooks"),
  usePHFeatureFlag: () => false,
}));

let defaultVision: DefaultModel | null = null;
let imageExtractionEnabled = true;

jest.mock("@/lib/languageModels/hooks", () => ({
  useAdminLanguageModels: () => ({
    llmProviders: [],
    defaultText: null,
    get defaultVision() {
      return defaultVision;
    },
    defaultChatNaming: null,
    defaultCraft: null,
    isLoading: false,
    error: undefined,
  }),
}));

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({
    appName: "Yahont",
    get image_extraction_and_analysis_enabled() {
      return imageExtractionEnabled;
    },
  }),
}));

describe("LanguageModelsPage — image captioning banner", () => {
  beforeEach(() => {
    defaultVision = null;
    imageExtractionEnabled = true;
  });

  test("shown when extraction is enabled and no vision default is set", () => {
    render(<LanguageModelsPage />);

    expect(
      screen.getByText("No model chosen for image captioning")
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Go to Index Settings/ })
    ).toHaveAttribute("href", "/admin/index-settings");
  });

  test("hidden once a vision default is chosen", () => {
    defaultVision = { provider_id: 1, model_name: "gpt-4o" };
    render(<LanguageModelsPage />);

    expect(
      screen.queryByText("No model chosen for image captioning")
    ).not.toBeInTheDocument();
  });

  test("hidden when image extraction is turned off", () => {
    imageExtractionEnabled = false;
    render(<LanguageModelsPage />);

    expect(
      screen.queryByText("No model chosen for image captioning")
    ).not.toBeInTheDocument();
  });
});
