/**
 * The Yahont provider modal.
 *
 * The provider is managed by the platform. The modal only lets an admin rename
 * it, choose which of its models are visible, tune per-model settings, and set
 * who has access. It has no connection fields, no way to fetch or add models,
 * and no auto-update switch. The backend enforces the same rules.
 */

import { render, screen } from "@tests/setup/test-utils";
import YahontModal from "@/sections/modals/languageModels/YahontModal";
import type {
  LLMProviderView,
  ModelConfiguration,
} from "@/lib/languageModels/types";

const mockMutate = jest.fn();
const mockRequestedKeys: unknown[] = [];
jest.mock("swr", () => {
  const actual = jest.requireActual("swr");
  return {
    ...actual,
    useSWRConfig: () => ({ mutate: mockMutate }),
    __esModule: true,
    default: (key: unknown) => {
      mockRequestedKeys.push(key);
      return { data: undefined, error: undefined, isLoading: false };
    },
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

jest.mock("@/lib/tiers/hooks", () => ({
  ...jest.requireActual("@/lib/tiers/hooks"),
  useTierAtLeast: () => false,
}));

function model(name: string, displayName: string): ModelConfiguration {
  return {
    id: 1,
    name,
    is_visible: true,
    max_input_tokens: 131072,
    supports_image_input: false,
    supports_reasoning: true,
    display_name: displayName,
    effectiveDisplayName: displayName,
  };
}

const YAHONT_PROVIDER: LLMProviderView = {
  id: 7,
  name: "Yahont",
  provider: "yahont",
  api_key: "****",
  api_base: null,
  api_version: null,
  custom_config: null,
  is_public: true,
  is_auto_mode: false,
  groups: [],
  personas: [],
  deployment_name: null,
  model_configurations: [
    model("deepseek/deepseek-v4-pro", "DeepSeek V4 Pro"),
    model("openai/gpt-oss-120b", "GPT-OSS 120B"),
  ],
};

describe("YahontModal", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRequestedKeys.length = 0;
    jest.spyOn(global, "fetch").mockResolvedValue(new Response("{}"));
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  test("shows the display name, the catalog models and the access setting", () => {
    render(<YahontModal existingLlmProvider={YAHONT_PROVIDER} />);

    expect(screen.getByPlaceholderText("Display Name")).toBeInTheDocument();
    expect(screen.getByText("DeepSeek V4 Pro")).toBeInTheDocument();
    expect(screen.getByText("GPT-OSS 120B")).toBeInTheDocument();
    expect(screen.getByText("Models Access")).toBeInTheDocument();
  });

  test("has no connection fields", () => {
    render(<YahontModal existingLlmProvider={YAHONT_PROVIDER} />);

    expect(screen.queryByText("API Base URL")).not.toBeInTheDocument();
    expect(screen.queryByText("API Key")).not.toBeInTheDocument();
  });

  test("cannot add models, fetch models or turn on auto-update", () => {
    render(<YahontModal existingLlmProvider={YAHONT_PROVIDER} />);

    expect(
      screen.queryByPlaceholderText("Enter model name")
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Add Model")).not.toBeInTheDocument();
    expect(screen.queryByText("Auto Update")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /refetch|refresh/i })
    ).not.toBeInTheDocument();
  });

  test("does not look up the provider among the well-known providers", () => {
    render(<YahontModal existingLlmProvider={YAHONT_PROVIDER} />);

    const requested = mockRequestedKeys.map((key) => String(key));
    expect(requested.some((key) => key.includes("/built-in/options"))).toBe(
      false
    );
  });
});
