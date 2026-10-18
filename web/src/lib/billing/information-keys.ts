import { mutate } from "swr";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { SWR_KEYS } from "@/lib/swr-keys";

/**
 * The billing-information key for THIS deployment. ONE source for the
 * reader (`useBillingInformation`) and the invalidators: a divergence
 * leaves the billing overview stale after every Manage Plan mutation —
 * the hook sets `revalidateIfStale: false`, so it never heals by itself.
 */
export function billingInformationKey(): string {
  return NEXT_PUBLIC_CLOUD_ENABLED
    ? SWR_KEYS.billingInformationCloud
    : SWR_KEYS.billingInformationSelfHosted;
}

/** Invalidate the billing-information entry on BOTH keys: mutating a key
 * nobody reads is a no-op, and the pair can never diverge from the reader. */
export async function invalidateBillingInformation(): Promise<void> {
  await Promise.all([
    mutate(SWR_KEYS.billingInformationCloud),
    mutate(SWR_KEYS.billingInformationSelfHosted),
  ]);
}
