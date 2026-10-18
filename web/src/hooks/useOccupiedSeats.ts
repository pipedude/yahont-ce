import useSWR from "swr";

import { errorHandlingFetcher } from "@/lib/fetcher";
import { SeatOccupancyResponse } from "@/lib/billing/types";
import { SWR_KEYS } from "@/lib/swr-keys";

/**
 * Fetch the occupied seat count from the unified predicate.
 *
 * The backend computes this via `get_occupied_seats` — the same predicate
 * used by `/seats/update` and `enforce_cloud_seat_limit`. The frontend
 * reads this number instead of computing `usedSeats + pendingSeats`
 * locally, so UI and server agree.
 */
export function useOccupiedSeats() {
  const { data, error, mutate, isLoading } = useSWR<SeatOccupancyResponse>(
    SWR_KEYS.occupiedSeats,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: false,
      dedupingInterval: 30000,
      shouldRetryOnError: false,
      keepPreviousData: true,
    }
  );

  return {
    data,
    error,
    refresh: mutate,
    isLoading,
  };
}
