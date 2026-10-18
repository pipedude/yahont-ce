/**
 * Voice provider cards in the cloud build.
 *
 * RouterAI and Polza.AI come first, under "{name} — Works in Russia without a
 * VPN". OpenAI, Azure and ElevenLabs do not serve Russia and stay hidden unless
 * a tenant already connected them. Zoom serves Russia and stays.
 */

import { render, screen } from "@tests/setup/test-utils";
import VoicePage from "@/views/admin/VoicePage";
import type { VoiceProviderView } from "@/lib/voice/types";

let mockProviders: VoiceProviderView[] = [];

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => "/admin/voice",
}));

jest.mock("@/lib/constants", () => ({
  ...jest.requireActual("@/lib/constants"),
  NEXT_PUBLIC_CLOUD_ENABLED: true,
}));

jest.mock("@/lib/voice/hooks", () => ({
  useVoiceProviders: () => ({
    providers: mockProviders,
    isLoading: false,
    refresh: jest.fn(),
  }),
}));

function openaiProvider(): VoiceProviderView {
  return {
    id: 1,
    name: "OpenAI",
    provider_type: "openai",
    is_default_stt: true,
    is_default_tts: false,
    stt_model: "whisper-1",
    tts_model: "tts-1",
    default_voice: "alloy",
    api_key: "sk-****",
    api_secret: null,
    target_uri: null,
    custom_config: null,
  };
}

describe("VoicePage in the cloud build", () => {
  beforeEach(() => {
    mockProviders = [];
  });

  test("offers the Russian gateways and Zoom only", () => {
    render(<VoicePage />);

    expect(
      screen.getAllByText("RouterAI — Works in Russia without a VPN")
    ).toHaveLength(2);
    expect(
      screen.getAllByText("Polza.AI — Works in Russia without a VPN")
    ).toHaveLength(2);
    for (const label of [
      "voice-stt-elevenlabs/scribe-v2",
      "voice-stt-openai/gpt-4o-transcribe",
      "voice-stt-scribe-live",
      "voice-tts-elevenlabs/eleven-v4",
      "voice-tts-elevenlabs/eleven-v4-turbo",
      "voice-tts-openai/tts-1",
      "voice-tts-openai/tts-1-hd",
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    for (const label of [
      "voice-stt-whisper",
      "voice-stt-azure-speech-stt",
      "voice-stt-elevenlabs-stt",
      "voice-tts-tts-1",
      "voice-tts-tts-1-hd",
      "voice-tts-azure-speech-tts",
      "voice-tts-elevenlabs-tts",
    ]) {
      expect(screen.queryByLabelText(label)).not.toBeInTheDocument();
    }
  });

  test("keeps a connected hidden vendor so it can be disconnected", () => {
    mockProviders = [openaiProvider()];

    render(<VoicePage />);

    expect(screen.getByLabelText("voice-stt-whisper")).toBeInTheDocument();
    expect(screen.getByLabelText("voice-tts-tts-1")).toBeInTheDocument();
    expect(
      screen.queryByLabelText("voice-stt-azure-speech-stt")
    ).not.toBeInTheDocument();
  });
});
