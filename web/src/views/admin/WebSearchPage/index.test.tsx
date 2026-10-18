/**
 * Web search provider cards in the cloud build.
 *
 * Exa (Cloudflare block for Russia) and Google PSE (closed to new customers)
 * are hidden unless a tenant already configured them. The other providers
 * reach their key check from Moscow and stay.
 */

import { render, screen } from "@tests/setup/test-utils";
import WebSearchPage from "@/views/admin/WebSearchPage";
import type {
  WebContentProviderView,
  WebSearchProviderView,
} from "@/lib/webSearch/types";

let mockSearchProviders: WebSearchProviderView[] = [];
let mockContentProviders: WebContentProviderView[] = [];

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => "/admin/web-search",
}));

jest.mock("@/lib/constants", () => ({
  ...jest.requireActual("@/lib/constants"),
  NEXT_PUBLIC_CLOUD_ENABLED: true,
}));

jest.mock("@/lib/webSearch/hooks", () => ({
  useWebSearchProviders: () => ({
    searchProviders: mockSearchProviders,
    contentProviders: mockContentProviders,
    searchProvidersError: undefined,
    contentProvidersError: undefined,
    isLoading: false,
    mutateSearchProviders: jest.fn(),
    mutateContentProviders: jest.fn(),
  }),
}));

// Card titles only: logos repeat the name in an SVG <title>.
function cardTitles(label: string): HTMLElement[] {
  return screen.queryAllByText(label, {
    selector: "[data-opal-content-title]",
  });
}

describe("WebSearchPage in the cloud build", () => {
  beforeEach(() => {
    mockSearchProviders = [];
    mockContentProviders = [];
  });

  test("hides Exa and Google PSE on both sides", () => {
    render(<WebSearchPage />);

    expect(cardTitles("Exa")).toHaveLength(0);
    expect(cardTitles("Google PSE")).toHaveLength(0);
    for (const label of ["Serper", "Brave", "SearXNG"]) {
      expect(cardTitles(label)).toHaveLength(1);
    }
    // Srezai, Tavily and Firecrawl have a search and a crawler card.
    for (const label of ["Srezai", "Tavily", "Firecrawl"]) {
      expect(cardTitles(label)).toHaveLength(2);
    }
  });

  test("keeps both Exa cards while one side is configured", () => {
    mockContentProviders = [
      {
        id: 7,
        name: "Exa",
        provider_type: "exa",
        is_active: false,
        config: null,
        masked_api_key: "exa-****",
      },
    ];

    render(<WebSearchPage />);

    expect(cardTitles("Exa")).toHaveLength(2);
    expect(cardTitles("Google PSE")).toHaveLength(0);
  });
});
