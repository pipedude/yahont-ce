/**
 * The Add Connector catalog hides sources that refuse Russian IPs, disable
 * accounts of Russian companies, or have no market in Russia. It does so in
 * every build, not only in the cloud: the cloud flag is off in these tests.
 * Notion, Slack, Bitbucket and the Microsoft 365 sources are shown by the
 * owner's decision; Confluence and Jira stay for self-hosted Server/Data
 * Center.
 */

import { render, screen } from "@tests/setup/test-utils";
import ConnectorsPage from "@/views/admin/connectors/CatalogPage";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => "/admin/add-connector",
}));

jest.mock("@/lib/connectors/hooks", () => ({
  ...jest.requireActual("@/lib/connectors/hooks"),
  useFederatedConnectors: () => ({ data: [] }),
}));

describe("Add Connector catalog (cloud and Community Edition)", () => {
  test("hides sources that do not serve Russia", () => {
    render(<ConnectorsPage />);

    for (const name of [
      "Linear",
      "Document360",
      "Gong",
      "HubSpot",
      "ClickUp",
      "Asana",
      "Airtable",
      "Salesforce",
      "Zendesk",
      "Axero",
      "Guru",
      "Loopio",
      "LumApps",
      "Slab",
      "Drupal Wiki",
      "Egnyte",
      "Box",
      "Oracle Storage",
      "R2",
      "Coda",
      "Productboard",
      "Fireflies",
      "Highspot",
      "Canvas",
    ]) {
      expect(screen.queryByText(name)).not.toBeInTheDocument();
    }
    for (const name of [
      "Confluence",
      "Jira",
      "Notion",
      "Slack",
      "Bitbucket",
      "SharePoint",
      "OneDrive",
      "Teams",
      "Outlook",
      "Google Drive",
      "GitHub",
    ]) {
      expect(screen.getAllByText(name).length).toBeGreaterThan(0);
    }
  });

  test("shows the Yandex Mail and Mail.ru cards", () => {
    render(<ConnectorsPage />);

    // The logo SVG <title> repeats a brand name, so a name can match twice.
    expect(screen.getAllByText("Яндекс Почта").length).toBeGreaterThan(0);
    expect(screen.getByText("Yandex Mail and Yandex 360")).toBeInTheDocument();
    expect(screen.getAllByText("Mail.ru").length).toBeGreaterThan(0);
    expect(screen.getByText("Mail.ru email")).toBeInTheDocument();
  });
});
