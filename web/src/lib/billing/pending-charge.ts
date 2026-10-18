/**
 * The pending charge across the ЮKassa redirect.
 *
 * The control plane creates the charge during the pay request, so the id cannot ride
 * the return_url; the frontend stores it before the redirect and reads it
 * on the return to poll the payment status.
 */

const PENDING_CHARGE_KEY = "billing_pending_charge";

export function rememberPendingCharge(chargeId: string | null): void {
  if (chargeId) {
    sessionStorage.setItem(PENDING_CHARGE_KEY, chargeId);
  }
}

export function takePendingCharge(): string | null {
  const chargeId = sessionStorage.getItem(PENDING_CHARGE_KEY);
  if (chargeId) {
    sessionStorage.removeItem(PENDING_CHARGE_KEY);
  }
  return chargeId;
}
