import { Formik } from "formik";
import { render, screen } from "@tests/setup/test-utils";
import { CredentialFieldsRenderer } from "@/lib/credentials/components/CredentialFieldsRenderer";
import { getCredentialSpec } from "@/lib/credentials/utils";
import { ValidSources } from "@/lib/connectors/types/source";
import englishMessages from "@/i18n/messages/en.json";

const hints = englishMessages.admin.credentials.hints;

function renderFields(source: ValidSources) {
  const spec = getCredentialSpec(source);
  if (!spec) throw new Error(`no credential spec for ${source}`);
  render(
    <Formik initialValues={{}} onSubmit={() => {}}>
      <CredentialFieldsRenderer source={source} spec={spec} />
    </Formik>
  );
}

describe("CredentialFieldsRenderer hints", () => {
  it("shows the hint of a text field", () => {
    renderFields(ValidSources.GitHub);

    expect(screen.getByText(hints.githubBaseUrl)).toBeInTheDocument();
  });

  it("shows the app password hints of the Yandex Mail preset", () => {
    renderFields(ValidSources.YandexMail);

    expect(screen.getByText(hints.yandexMailLogin)).toBeInTheDocument();
    expect(screen.getByText(hints.yandexMailAppPassword)).toBeInTheDocument();
  });

  it("shows the app password hints of the Mail.ru preset", () => {
    renderFields(ValidSources.MailruMail);

    expect(screen.getByText(hints.mailruMailLogin)).toBeInTheDocument();
    expect(screen.getByText(hints.mailruMailAppPassword)).toBeInTheDocument();
  });
});
