"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import ProviderCard from "@/sections/admin/ProviderCard";
import { SettingsLayouts } from "@opal/layouts";
import { useVoiceProviders } from "@/lib/voice/hooks";
import {
  activateVoiceProvider,
  deactivateVoiceProvider,
} from "@/lib/voice/svc";
import { PageLoader } from "@opal/loaders";
import { Content } from "@opal/layouts";
import { MessageCard, Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useCreateModal } from "@opal/components";
import {
  VoiceProviderSetupModal,
  VoiceDisconnectModal,
  type ProviderMode,
} from "@/views/admin/VoicePage/shared";
import { getVoiceProviderDetail } from "@/lib/voice/utils";
import { VoiceProviderView } from "@/lib/voice/types";
import { isVoiceProviderHiddenInCloud } from "@/lib/languageModels/cloudVisibility";

// Message keys, not copy — the literal union keeps `t()` statically checked.
type ModelSubtitleKey =
  | "models.whisper.subtitle"
  | "models.azureSpeechStt.subtitle"
  | "models.elevenlabsStt.subtitle"
  | "models.zoomScribe.subtitle"
  | "models.tts1.subtitle"
  | "models.tts1Hd.subtitle"
  | "models.azureSpeechTts.subtitle"
  | "models.elevenlabsTts.subtitle"
  | "models.scribeV2.subtitle"
  | "models.gpt4oTranscribe.subtitle"
  | "models.elevenV4.subtitle"
  | "models.elevenV4Turbo.subtitle";

interface ModelDetails {
  id: string;
  // Model name — a proper noun, so it is not translated.
  label: string;
  subtitleKey: ModelSubtitleKey;
  providerType: string;
}

interface ProviderGroup {
  providerType: string;
  // Vendor name — a proper noun, so it is not translated.
  providerLabel: string;
  // Russian gateways: "{name} — Works in Russia without a VPN".
  titleKey?: "providerGroups.worksInRussia.title";
  models: ModelDetails[];
}

// Card ids of the gateways are the API model ids (backend gateway.py).
const STT_PROVIDER_GROUPS: ProviderGroup[] = [
  {
    providerType: "routerai",
    providerLabel: "RouterAI",
    titleKey: "providerGroups.worksInRussia.title",
    models: [
      {
        id: "elevenlabs/scribe-v2",
        label: "ElevenLabs Scribe v2",
        subtitleKey: "models.scribeV2.subtitle",
        providerType: "routerai",
      },
    ],
  },
  {
    providerType: "polza",
    providerLabel: "Polza.AI",
    titleKey: "providerGroups.worksInRussia.title",
    models: [
      {
        id: "openai/gpt-4o-transcribe",
        label: "GPT-4o Transcribe",
        subtitleKey: "models.gpt4oTranscribe.subtitle",
        providerType: "polza",
      },
    ],
  },
  {
    providerType: "openai",
    providerLabel: "OpenAI",
    models: [
      {
        id: "whisper",
        label: "Whisper",
        subtitleKey: "models.whisper.subtitle",
        providerType: "openai",
      },
    ],
  },
  {
    providerType: "azure",
    providerLabel: "Azure",
    models: [
      {
        id: "azure-speech-stt",
        label: "Azure Speech",
        subtitleKey: "models.azureSpeechStt.subtitle",
        providerType: "azure",
      },
    ],
  },
  {
    providerType: "elevenlabs",
    providerLabel: "ElevenLabs",
    models: [
      {
        id: "elevenlabs-stt",
        label: "ElevenAPI",
        subtitleKey: "models.elevenlabsStt.subtitle",
        providerType: "elevenlabs",
      },
    ],
  },
  {
    providerType: "zoom",
    providerLabel: "Zoom",
    models: [
      {
        id: "scribe-live",
        label: "Zoom Scribe",
        subtitleKey: "models.zoomScribe.subtitle",
        providerType: "zoom",
      },
    ],
  },
];

// TTS Models - grouped by provider
const TTS_PROVIDER_GROUPS: ProviderGroup[] = [
  {
    providerType: "routerai",
    providerLabel: "RouterAI",
    titleKey: "providerGroups.worksInRussia.title",
    models: [
      {
        id: "elevenlabs/eleven-v4",
        label: "Eleven v4",
        subtitleKey: "models.elevenV4.subtitle",
        providerType: "routerai",
      },
      {
        id: "elevenlabs/eleven-v4-turbo",
        label: "Eleven v4 Turbo",
        subtitleKey: "models.elevenV4Turbo.subtitle",
        providerType: "routerai",
      },
    ],
  },
  {
    providerType: "polza",
    providerLabel: "Polza.AI",
    titleKey: "providerGroups.worksInRussia.title",
    models: [
      {
        id: "openai/tts-1",
        label: "TTS-1",
        subtitleKey: "models.tts1.subtitle",
        providerType: "polza",
      },
      {
        id: "openai/tts-1-hd",
        label: "TTS-1 HD",
        subtitleKey: "models.tts1Hd.subtitle",
        providerType: "polza",
      },
    ],
  },
  {
    providerType: "openai",
    providerLabel: "OpenAI",
    models: [
      {
        id: "tts-1",
        label: "TTS-1",
        subtitleKey: "models.tts1.subtitle",
        providerType: "openai",
      },
      {
        id: "tts-1-hd",
        label: "TTS-1 HD",
        subtitleKey: "models.tts1Hd.subtitle",
        providerType: "openai",
      },
    ],
  },
  {
    providerType: "azure",
    providerLabel: "Azure",
    models: [
      {
        id: "azure-speech-tts",
        label: "Azure Speech",
        subtitleKey: "models.azureSpeechTts.subtitle",
        providerType: "azure",
      },
    ],
  },
  {
    providerType: "elevenlabs",
    providerLabel: "ElevenLabs",
    models: [
      {
        id: "elevenlabs-tts",
        label: "ElevenAPI",
        subtitleKey: "models.elevenlabsTts.subtitle",
        providerType: "elevenlabs",
      },
    ],
  },
];

const route = ADMIN_ROUTES.VOICE;

interface ModelCardProps {
  model: ModelDetails;
  mode: ProviderMode;
  provider: VoiceProviderView | undefined;
  status: "disconnected" | "connected" | "selected";
  hasAlternatives: boolean;
  onSelect: () => void;
  onDeselect: () => void;
  onMutate: () => void;
}

function ModelCard({
  model,
  mode,
  provider,
  status,
  hasAlternatives,
  onSelect,
  onDeselect,
  onMutate,
}: ModelCardProps) {
  const t = useTranslations("admin.voice");
  const setupModal = useCreateModal();
  const disconnectModal = useCreateModal();

  return (
    <>
      <setupModal.Provider>
        <VoiceProviderSetupModal
          providerType={model.providerType}
          existingProvider={
            status !== "disconnected" ? (provider ?? null) : null
          }
          mode={mode}
          defaultModelId={model.id}
          onSuccess={() => {
            onMutate();
            setupModal.toggle(false);
          }}
        />
      </setupModal.Provider>

      <disconnectModal.Provider>
        <VoiceDisconnectModal
          disconnectTarget={{
            providerId: provider?.id ?? 0,
            providerLabel: getVoiceProviderDetail(model.providerType).label,
            providerType: model.providerType,
          }}
          hasAlternatives={hasAlternatives}
          onSuccess={() => onMutate()}
        />
      </disconnectModal.Provider>

      <ProviderCard
        aria-label={`voice-${mode}-${model.id}`}
        icon={getVoiceProviderDetail(model.providerType).icon}
        title={model.label}
        description={t(model.subtitleKey)}
        status={status}
        onConnect={() => setupModal.toggle(true)}
        onSelect={onSelect}
        onDeselect={onDeselect}
        onEdit={() => setupModal.toggle(true)}
        onDisconnect={
          status !== "disconnected" && provider
            ? () => disconnectModal.toggle(true)
            : undefined
        }
        disconnectModalOpen={disconnectModal.isOpen}
      />
    </>
  );
}

export default function VoicePage() {
  const t = useTranslations("admin.voice");
  const { providers, isLoading, refresh: mutate } = useVoiceProviders();

  const providersByType = useMemo(() => {
    return new Map((providers ?? []).map((p) => [p.provider_type, p] as const));
  }, [providers]);

  const hasActiveSTTProvider =
    providers?.some((p) => p.is_default_stt) ?? false;
  const hasActiveTTSProvider =
    providers?.some((p) => p.is_default_tts) ?? false;

  if (isLoading) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={t("header.title")}
          description={t("header.description")}
          divider
        />
        <SettingsLayouts.Body>
          <PageLoader />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  const getModelStatus = (
    model: ModelDetails,
    mode: ProviderMode
  ): "disconnected" | "connected" | "selected" => {
    const provider = providersByType.get(model.providerType);
    if (!provider || !provider.api_key) return "disconnected";

    const isActive =
      mode === "stt"
        ? provider.is_default_stt
        : provider.is_default_tts && provider.tts_model === model.id;

    if (isActive) return "selected";
    return "connected";
  };

  // Cloud build: vendors that do not serve Russia stay visible only if connected.
  const renderGroups = (groups: ProviderGroup[], mode: ProviderMode) => (
    <Section gap={4}>
      {groups
        .map((group) => ({
          ...group,
          models: group.models.filter(
            (model) =>
              getModelStatus(model, mode) !== "disconnected" ||
              !isVoiceProviderHiddenInCloud(model.providerType)
          ),
        }))
        .filter((group) => group.models.length > 0)
        .map((group) => (
          <div key={group.providerType} className="flex w-full flex-col gap-2">
            <Text font="secondary-body" color="text-03">
              {group.titleKey
                ? t(group.titleKey, { name: group.providerLabel })
                : group.providerLabel}
            </Text>
            {group.models.map((model) => (
              <ModelCard
                key={`${mode}-${model.id}`}
                model={model}
                mode={mode}
                provider={providersByType.get(model.providerType)}
                status={getModelStatus(model, mode)}
                hasAlternatives={
                  (providers ?? []).filter(
                    (p) => p.provider_type !== model.providerType && !!p.api_key
                  ).length > 0
                }
                onSelect={() => {
                  const p = providersByType.get(model.providerType);
                  if (p?.id)
                    activateVoiceProvider(p.id, mode, model.id).then(() =>
                      mutate()
                    );
                }}
                onDeselect={() => {
                  const p = providersByType.get(model.providerType);
                  if (p?.id)
                    deactivateVoiceProvider(p.id, mode).then(() => mutate());
                }}
                onMutate={() => mutate()}
              />
            ))}
          </div>
        ))}
    </Section>
  );

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={t("header.title")}
        description={t("header.description")}
        divider
      />
      <SettingsLayouts.Body>
        <Section gap={8}>
          <Section gap={3}>
            <Content
              title={t("speechToText.title")}
              description={t("speechToText.description")}
              sizePreset="main-content"
              variant="section"
            />

            {!hasActiveSTTProvider && (
              <MessageCard
                variant="info"
                title={t("speechToText.emptyState.title")}
              />
            )}

            {renderGroups(STT_PROVIDER_GROUPS, "stt")}
          </Section>

          <Section gap={3}>
            <Content
              title={t("textToSpeech.title")}
              description={t("textToSpeech.description")}
              sizePreset="main-content"
              variant="section"
            />

            {!hasActiveTTSProvider && (
              <MessageCard
                variant="info"
                title={t("textToSpeech.emptyState.title")}
              />
            )}

            {renderGroups(TTS_PROVIDER_GROUPS, "tts")}
          </Section>
        </Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
