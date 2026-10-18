/**
 * Human-readable cancellation reasons.
 *
 * Without this map the user sees `payment_method_restricted` and goes to
 * support. ЮKassa's `cancellation_reason` values are stable; anything
 * unknown falls back to the generic message (the word "потерян" never
 * appears next to an amount without an explanation).
 *
 * The strings live in the i18n catalogs (`admin.billing.declineReasons`):
 * a hardcoded Russian sentence inside a non-Russian UI fell back to the
 * system font and rendered at a different size than the banner around it.
 */

import { useTranslations } from "next-intl";

/** ЮKassa decline codes with a catalog entry — everything else collapses
 *  to `fallback`. */
const DECLINE_KEYS = [
  "fallback",
  "insufficient_funds",
  "card_expired",
  "payment_method_restricted",
  "permission_revoked",
  "issuer_unavailable",
  "payment_method_limit_exceeded",
  "3d_secure_failed",
  "invalid_card_number",
  "invalid_csc",
  "fraud_suspected",
  "country_forbidden",
  "call_issuer",
  "general_decline",
  "expired_on_confirmation",
  "internal_timeout",
  "identification_required",
] as const;

type DeclineKey = (typeof DECLINE_KEYS)[number];
const KNOWN_REASONS = new Set<string>(DECLINE_KEYS);
const isDeclineKey = (v: string): v is DeclineKey => KNOWN_REASONS.has(v);

/** Returns `(reason) => localized message`. A hook because the strings
 *  are catalog lookups — call it once per component. */
export function useDeclineMessage() {
  const t = useTranslations("admin.billing.declineReasons");
  return (reason?: string | null): string => {
    const key: DeclineKey =
      reason && isDeclineKey(reason) ? reason : "fallback";
    return t(key);
  };
}
