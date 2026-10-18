"use client";

import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { useTranslations } from "next-intl";
import { useSettings } from "@/lib/settings/hooks";
import { ErrorCallout } from "@/components/ErrorCallout";
import { PageLoader } from "@opal/loaders";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { SlackBotTable } from "./SlackBotTable";
import { useSlackBots } from "./[bot-id]/hooks";
import { SettingsLayouts } from "@opal/layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Button, MessageCard } from "@opal/components";
import { SvgPlusCircle } from "@opal/icons";

const route = ADMIN_ROUTES.SLACK_BOTS;

function Main() {
  const t = useTranslations("admin.slackBots");
  const tTelegram = useTranslations("admin.telegramBots");
  const { appName } = useSettings();
  const {
    data: slackBots,
    isLoading: isSlackBotsLoading,
    error: slackBotsError,
  } = useSlackBots();

  if (isSlackBotsLoading) {
    return <PageLoader />;
  }

  if (slackBotsError || !slackBots) {
    const errorMsg =
      slackBotsError?.info?.message ||
      slackBotsError?.info?.detail ||
      t("error.unknownOccurred.message");

    return (
      <ErrorCallout
        errorTitle={t("list.error.title")}
        errorMsg={`${errorMsg}`}
      />
    );
  }

  // Yahont: the page announces the Telegram integration, which is not built
  // yet, so bot creation is off. Slack bots created earlier stay manageable.
  return (
    <div className="mb-8">
      <div className="mb-6">
        <MessageCard
          variant="info"
          title={tTelegram("inDevelopment.title")}
          description={tTelegram("inDevelopment.description")}
        />
      </div>

      <p className="mb-2 text-sm text-muted-foreground">
        {tTelegram("intro.description", { appName })}
      </p>

      <div className="mb-6">
        <ul className="list-disc mt-2 ms-4 text-sm text-muted-foreground">
          <li>{tTelegram("intro.autoAnswer.item")}</li>
          <li>{tTelegram("intro.documentSets.item")}</li>
          <li>{tTelegram("intro.directMessage.item")}</li>
        </ul>
      </div>

      <Button icon={SvgPlusCircle} prominence="secondary" disabled>
        {tTelegram("newBotButton.label")}
      </Button>

      {slackBots.length > 0 && <SlackBotTable slackBots={slackBots} />}
    </div>
  );
}

export default function Page() {
  const adminRouteTitle = useAdminRouteTitle();
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={adminRouteTitle(route)}
        divider
      />
      <SettingsLayouts.Body>
        <InstantSSRAutoRefresh />
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
