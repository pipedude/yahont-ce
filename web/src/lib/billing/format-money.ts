/**
 * Money formatting for the ЮKassa billing UI.
 *
 * The control plane carries amounts as decimal strings ("12345.67") and the
 * tenant wallet as integer cents. Both render through here so every surface
 * shows the same ru-RU form: "12 345,67 ₽".
 */

const RUB_FORMAT = new Intl.NumberFormat("ru-RU", {
  style: "currency",
  currency: "RUB",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const RUB_FORMAT_WHOLE = new Intl.NumberFormat("ru-RU", {
  style: "currency",
  currency: "RUB",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

/** Kopecks → «12 345,67 ₽». Negative values are clamped to zero: a stale
 * negative wallet snapshot must not render negative rubles. */
export function formatMoney(kopecks: number): string {
  return RUB_FORMAT.format(Math.max(0, kopecks) / 100);
}

/** Kopecks → «1 590 ₽» — the compact button form. Package prices are whole
 * rubles; kopeck decimals on a button read as noise. */
export function formatMoneyWhole(kopecks: number): string {
  return RUB_FORMAT_WHOLE.format(Math.max(0, kopecks) / 100);
}

/** Parse a billing service amount string ("12345.67") into kopecks. */
export function parseAmountToKop(amount: string): number {
  return Math.round(Number.parseFloat(amount) * 100);
}

/** Format a billing service amount string ("12345.67") for display. */
export function formatCpAmount(amount: string): string {
  return RUB_FORMAT.format(Number.parseFloat(amount));
}

/**
 * USD cents (the tenant wallet) → kopecks at the package's anchor rate:
 * packagePriceKop per packageUsdCents, e.g. 1 590,00 ₽ per 1 800 $ of
 * credits. Zero inputs yield zero — the indicator hides until the first
 * grant anyway.
 */
export function usdCentsToKop(
  usdCents: number,
  packagePriceKop: number,
  packageUsdCents: number
): number {
  if (packagePriceKop <= 0 || packageUsdCents <= 0) {
    return 0;
  }
  return Math.round((usdCents / packageUsdCents) * packagePriceKop);
}
