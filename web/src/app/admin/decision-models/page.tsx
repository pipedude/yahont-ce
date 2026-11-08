import { notFound } from "next/navigation";
import { DECISION_MODELS_HIDDEN } from "@/lib/languageModels/cloudVisibility";
import DecisionModelsPage from "@/views/admin/DecisionModelsPage";

export default function Page() {
  if (DECISION_MODELS_HIDDEN) notFound();
  return <DecisionModelsPage />;
}
