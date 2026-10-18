/**
 * The "add a provider" cards of the Language Models page.
 *
 * RouterAI and Polza.ai work in Russia without a VPN, and their cards say so
 * instead of repeating the company name. Other cards keep the company name.
 */

import { render, screen } from "@tests/setup/test-utils";
import { NewProviderCard } from "@/views/admin/LanguageModelsPage";

jest.mock("@/hooks/useTierAtLeast", () => ({
  useTierAtLeast: () => false,
}));

describe("NewProviderCard", () => {
  test.each([
    ["routerai", "RouterAI", "routerai.ru"],
    ["polza", "Polza.ai", "polza.ai"],
  ])("%s says it works in Russia without a VPN", (name, product, company) => {
    render(<NewProviderCard providerName={name} isFirstProvider={false} />);

    expect(
      screen.getByText("Works in Russia without a VPN")
    ).toBeInTheDocument();
    expect(screen.queryByText(company)).not.toBeInTheDocument();
    // The accessible name still carries the company, so callers can find it.
    expect(
      screen.getByLabelText(`Add ${company} ${product}`)
    ).toBeInTheDocument();
  });

  test("other providers keep the company name", () => {
    render(
      <NewProviderCard providerName="openrouter" isFirstProvider={false} />
    );

    expect(
      screen.getByLabelText("Add OpenRouter OpenRouter")
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Works in Russia without a VPN")
    ).not.toBeInTheDocument();
  });
});
