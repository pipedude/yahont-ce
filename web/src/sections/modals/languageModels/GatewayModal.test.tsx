/**
 * The RouterAI and Polza.ai connection forms.
 *
 * Both gateways are OpenAI-compatible: the admin gets the gateway's base URL
 * prefilled, enters an API key, and loads the model list from the gateway.
 * There is no auto-update switch because the model list comes straight from
 * the gateway.
 */

import type { ReactElement } from "react";
import { act } from "@testing-library/react";
import { render, screen } from "@tests/setup/test-utils";
import PolzaModal from "@/sections/modals/languageModels/PolzaModal";
import RouterAIModal from "@/sections/modals/languageModels/RouterAIModal";
import { POLZA_URL, ROUTERAI_URL } from "@/lib/languageModels/gatewayLinks";

const mockMutate = jest.fn();
jest.mock("swr", () => {
  const actual = jest.requireActual("swr");
  return {
    ...actual,
    useSWRConfig: () => ({ mutate: mockMutate }),
    __esModule: true,
    default: () => ({ data: undefined, error: undefined, isLoading: false }),
  };
});

jest.mock("@opal/layouts/toast/store", () => {
  const toastFn = Object.assign(jest.fn(), {
    success: jest.fn(),
    error: jest.fn(),
    info: jest.fn(),
    warning: jest.fn(),
    dismiss: jest.fn(),
    clearAll: jest.fn(),
    _markLeaving: jest.fn(),
  });
  return {
    toast: toastFn,
    useToast: () => ({
      toast: toastFn,
      dismiss: toastFn.dismiss,
      clearAll: toastFn.clearAll,
    }),
  };
});

jest.mock("@/hooks/useTierAtLeast", () => ({
  useTierAtLeast: () => false,
}));

async function renderModal(ui: ReactElement) {
  // Formik validates on mount; let that settle inside act().
  await act(async () => {
    render(ui);
  });
}

describe.each([
  [
    "RouterAI",
    RouterAIModal,
    "https://routerai.ru/api/v1",
    "RouterAI endpoint URL (including API version).",
    "routerai.ru",
    ROUTERAI_URL,
  ],
  [
    "Polza.ai",
    PolzaModal,
    "https://polza.ai/api/v1",
    "Polza.ai endpoint URL (including API version).",
    "polza.ai",
    POLZA_URL,
  ],
])(
  "%s modal",
  (product, Modal, defaultBase, baseDescription, company, siteUrl) => {
    beforeEach(() => {
      jest.clearAllMocks();
    });

    test("prefills the gateway's base URL", async () => {
      await renderModal(<Modal />);

      expect(screen.getByDisplayValue(defaultBase)).toBeInTheDocument();
      expect(screen.getByText(baseDescription)).toBeInTheDocument();
    });

    test("asks for an API key", async () => {
      await renderModal(<Modal />);

      expect(screen.getByText("API Key")).toBeInTheDocument();
    });

    test("has no auto-update switch", async () => {
      await renderModal(<Modal />);

      expect(screen.queryByText("Auto Update")).not.toBeInTheDocument();
    });

    test("links the company in the header to the gateway's site in a new window", async () => {
      await renderModal(<Modal />);

      const link = screen.getByRole("link", { name: company });

      expect(link).toHaveAttribute("href", siteUrl);
      expect(link).toHaveAttribute("target", "_blank");
    });

    test("points the API key hint at the same site", async () => {
      await renderModal(<Modal />);

      const link = screen.getByRole("link", { name: product });

      expect(link).toHaveAttribute("href", siteUrl);
      expect(link).toHaveAttribute("target", "_blank");
    });

    test("keeps a saved base URL when editing", async () => {
      await renderModal(
        <Modal
          existingLlmProvider={{
            id: 4,
            name: "Gateway",
            provider: "routerai",
            api_key: "abcd****wxyz",
            api_base: "https://proxy.example/v1",
            api_version: null,
            custom_config: null,
            is_public: true,
            is_auto_mode: false,
            groups: [],
            personas: [],
            deployment_name: null,
            model_configurations: [],
          }}
        />
      );

      expect(
        screen.getByDisplayValue("https://proxy.example/v1")
      ).toBeInTheDocument();
      expect(screen.queryByDisplayValue(defaultBase)).not.toBeInTheDocument();
    });
  }
);
