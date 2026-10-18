"use client";

/**
 * Poll a charge's status after the ЮKassa return.
 *
 * The webhook may land seconds after the user is back on return_url;
 * without polling the UI would show the stale state and the admin would
 * assume the payment failed. Poll every 2 s for at most 30 s — past the
 * deadline the honest answer is "still processing", not a spinner forever.
 * A pending result is never success.
 */

import { useEffect, useRef } from "react";

import { getChargeStatus } from "@/lib/billing/svc";
import type { ChargeStatus } from "@/lib/billing/types";

const POLL_INTERVAL_MS = 2_000;
const POLL_DEADLINE_MS = 30_000;

export type ChargePollOutcome =
  | { kind: "settled"; charge: ChargeStatus }
  | { kind: "still_processing" };

export function useChargeStatusPolling() {
  const timerRef = useRef<number | null>(null);

  const stop = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  useEffect(() => stop, []);

  const start = (
    chargeId: string,
    onDone: (outcome: ChargePollOutcome) => void
  ) => {
    stop();
    const deadline = Date.now() + POLL_DEADLINE_MS;

    const tick = async () => {
      try {
        const charge = await getChargeStatus(chargeId);
        if (charge.status === "succeeded" || charge.status === "canceled") {
          onDone({ kind: "settled", charge });
          return;
        }
      } catch {
        // A transport error while polling is not a payment failure: keep
        // polling until the deadline.
      }
      if (Date.now() >= deadline) {
        onDone({ kind: "still_processing" });
        return;
      }
      timerRef.current = window.setTimeout(tick, POLL_INTERVAL_MS);
    };
    void tick();
  };

  return { start, stop };
}
