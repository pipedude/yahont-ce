import useSWR from "swr";

import { errorHandlingFetcher } from "@/lib/fetcher";
import { billingInformationKey } from "@/lib/billing/information-keys";
import { BillingInformation, SubscriptionStatus } from "@/lib/billing/types";

/**
 * Hook to fetch billing information.
 *
 * Works for both cloud and self-hosted deployments:
 * - Cloud: fetches from /api/tenants/billing-information
 * - Self-hosted: fetches from /api/admin/billing/billing-information
 *
 * The key comes from `billingInformationKey()` — the invalidators use the
 * same module, so the reader and the invalidators cannot diverge.
 */
export function useBillingInformation() {
  const url = billingInformationKey();

  const { data, error, mutate, isLoading } = useSWR<
    BillingInformation | SubscriptionStatus
  >(url, errorHandlingFetcher, {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    revalidateIfStale: false,
    dedupingInterval: 30000,
    shouldRetryOnError: false,
    keepPreviousData: true,
  });

  return { data, isLoading, error, refresh: mutate };
}
