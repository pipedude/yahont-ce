/**
 * The tariff catalog types, mirroring the billing service wire models
 * (`PlanCatalogResponse`) with `extra="forbid"` semantics enforced on the
 * billing service side. Amounts are decimal strings.
 */

import { parseAmountToKop } from "./format-money";

export interface PlanModel {
  code: string;
  title: string;
  period: string;
  price_monthly: string;
  solo_price_monthly: string;
  trial_days: number;
  self_serve: boolean;
  vat_code: number;
}

export interface LlmPackageModel {
  price: string;
  usd_cents: number;
  max_per_charge: number;
}

export interface PlanCatalog {
  currency: string;
  plans: PlanModel[];
  llm_package: LlmPackageModel;
}

/** The launch catalog has exactly one self-serve SKU. */
export const BUSINESS_PLAN_CODE = "business";
export const BILLING_PERIOD = "monthly";

/**
 * The control plane's `billable_amount` rule, mirrored for DISPLAY ONLY: one
 * seat bills the solo price, two or more bill the per-seat price each. The
 * control plane stays authoritative — it re-derives every amount from its
 * own catalog and DB, so a drift here can mislead the label but never the
 * money.
 */
export function billableAmountKop(seats: number, plan: PlanModel): number {
  if (seats <= 0) {
    return 0;
  }
  const perSeat = parseAmountToKop(plan.price_monthly);
  return seats === 1
    ? parseAmountToKop(plan.solo_price_monthly)
    : seats * perSeat;
}
