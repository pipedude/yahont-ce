/**
 * The bots page announces the Telegram integration, which is in development:
 * an info banner, Telegram wording, and a disabled "new bot" button. Slack
 * bots created earlier are still listed so an admin can manage them.
 */

import { render, screen } from "@tests/setup/test-utils";
import Page from "@/app/admin/bots/page";

let mockSlackBots: { id: number; name: string }[] = [];

jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
    refresh: jest.fn(),
  }),
  usePathname: () => "/admin/bots",
}));

jest.mock("@/app/admin/bots/[bot-id]/hooks", () => ({
  useSlackBots: () => ({
    data: mockSlackBots,
    isLoading: false,
    error: undefined,
  }),
}));

jest.mock("@/app/admin/bots/SlackBotTable", () => ({
  SlackBotTable: () => <div data-testid="slack-bot-table" />,
}));

describe("Telegram integration page", () => {
  beforeEach(() => {
    mockSlackBots = [];
  });

  test("shows the in-development banner and a disabled create button", () => {
    render(<Page />);

    expect(
      screen.getByText("Telegram integration is in development")
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "New Telegram Bot" })
    ).toBeDisabled();
    expect(screen.queryByText(/Slack/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("slack-bot-table")).not.toBeInTheDocument();
  });

  test("still lists Slack bots created earlier", () => {
    mockSlackBots = [{ id: 1, name: "legacy" }];

    render(<Page />);

    expect(screen.getByTestId("slack-bot-table")).toBeInTheDocument();
  });
});
