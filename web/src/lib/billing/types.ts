/**
 * Billing and License interfaces.
 *
 * These types match the backend Pydantic models:
 * - LicenseStatusResponse (backend/ee/onyx/server/license/models.py)
 * - BillingInformationResponse (backend/ee/onyx/server/billing/models.py)
 */

// ----------------------------------------------------------------------------
// License Types (Self-hosted only)
// ----------------------------------------------------------------------------

export type PlanType = "monthly" | "annual";

export type LicenseSource = "auto_fetch" | "manual_upload";

export type ApplicationStatus =
  | "active"
  | "payment_reminder"
  | "gated_access"
  | "expired"
  | "seat_limit_exceeded";

export type ExpiryWarningStage = "none" | "t_30d" | "t_14d" | "t_1d" | "grace";

/**
 * Billing status of the cloud subscription (Control Plane).
 */
export enum BillingStatus {
  TRIALING = "trialing",
  ACTIVE = "active",
  // `cancelled` is the legacy Stripe spelling; the Control Plane sends
  // `canceled` — both stay mapped.
  CANCELLED = "cancelled",
  CANCELED = "canceled",
  EXPIRED = "expired",
  PAST_DUE = "past_due",
  UNPAID = "unpaid",
}

/**
 * License status response from /api/license endpoint.
 * Only relevant for self-hosted deployments.
 */
export interface LicenseStatus {
  has_license: boolean;
  seats: number;
  used_seats: number;
  plan_type: PlanType | null;
  issued_at: string | null;
  expires_at: string | null;
  grace_period_end: string | null;
  status: ApplicationStatus | null;
  expiry_warning_stage: ExpiryWarningStage;
  source: LicenseSource | null;
  trial_end: string | null;
}

// ----------------------------------------------------------------------------
// Billing Types (Cloud and Self-hosted)
// ----------------------------------------------------------------------------

/**
 * Billing information of the cloud subscription.
 * Available for both cloud and self-hosted with active subscription.
 */
export interface BillingInformation {
  tenant_id: string;
  status: string | null;
  plan_type: string | null;
  seats: number | null;
  billing_period: string | null;
  current_period_start: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  canceled_at: string | null;
  trial_start: string | null;
  trial_end: string | null;
  payment_method_enabled: boolean;
  // LLM credit wallet — owned by the tenant, nullable until the first
  // grant; never cached (it moves on every LLM call).
  llm_credit_balance_cents: number | null;
  llm_credit_total_granted_cents: number | null;
  // The planned decrease and the past_due grace end: the state banners read
  // both from the snapshot.
  pending_quantity_decrease: number | null;
  grace_ends_at: string | null;
}

/**
 * Response when no subscription exists.
 */
export interface SubscriptionStatus {
  subscribed: boolean;
}

// ----------------------------------------------------------------------------
// Checkout & Portal Types
// ----------------------------------------------------------------------------

export interface CreateCheckoutSessionRequest {
  billing_period?: "monthly" | "annual";
  seats?: number;
  email?: string;
  /** Where the provider returns the user. The caller passes its own
   * origin — the session cookie is host-bound, so a return to any other
   * host lands on /auth/login (the same contract as `payInvoice` and
   * the payment-method binding). WEB_DOMAIN is the server-side
   * fallback when omitted. */
  return_url?: string;
}

export interface CreateCheckoutSessionResponse {
  checkout_url: string;
  /** The control plane's charge for this checkout: the return polls its
   * status — the charge is created during the request, so the id travels
   * through sessionStorage, not the return_url. */
  charge_id: string | null;
}

// ----------------------------------------------------------------------------
// Seat Management Types
// ----------------------------------------------------------------------------

export interface SeatUpdateRequest {
  new_seat_count: number;
}

export interface SeatUpdateResponse {
  success: boolean;
  current_seats: number;
  used_seats: number;
  message: string | null;
}

export interface CommunityDowngradeResponse {
  connectors_made_public: number;
  user_groups_removed: number;
}

// Occupied seat count from the unified predicate.
// The frontend reads this instead of computing usedSeats + pendingSeats
// locally, so UI and server agree.
export interface SeatOccupancyResponse {
  occupied_seats: number;
}

// ----------------------------------------------------------------------------
// Manage Plan wire types — mirrors of the billing service models
// (extra="forbid"). Dates are ISO strings; amounts are decimal strings
// ("12345.67").
// ----------------------------------------------------------------------------

export interface SubscriptionSnapshot {
  subscription_id: string;
  tenant_id: string;
  status: string;
  quantity: number;
  pending_quantity_decrease: number | null;
  current_period_start: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
}

export interface PlanLine {
  description: string;
  quantity: string;
  amount: string;
}

export interface ProrationPreview {
  currency: string;
  lines: PlanLine[];
  subtotal: string;
  total: string;
  effective_at: string | null;
  new_period_start: string | null;
  new_period_end: string | null;
  requires_payment: boolean;
  note: string | null;
}

export interface PlanUpdateResponse {
  applied: boolean;
  scheduled: boolean;
  requires_payment: boolean;
  pending_quantity_decrease: number | null;
  effective_at: string | null;
  subscription: SubscriptionSnapshot | null;
  note: string | null;
  invoice_id: string | null;
  charge_id: string | null;
  charged: string | null;
  confirmation_url: string | null;
  amount: string | null;
  recalculated_total: string | null;
}

export interface PlanChangeRequest {
  quantity: number;
  plan_code: string;
  period: string;
}

export interface PlanUpdateRequest extends PlanChangeRequest {
  confirm_total?: string | null;
  return_url?: string | null;
}

// ----------------------------------------------------------------------------
// Payment Methods
// ----------------------------------------------------------------------------

export interface PaymentMethod {
  id: string;
  yk_payment_method_id: string | null;
  type: string | null;
  status: string | null;
  is_default: boolean;
  title: string | null;
  card_first6: string | null;
  card_last4: string | null;
  card_expiry_month: number | null;
  card_expiry_year: number | null;
  card_type: string | null;
  issuer_name: string | null;
}

export interface PaymentMethodListResponse {
  payment_methods: PaymentMethod[];
}

export interface BindingResponse {
  confirmation_url: string;
  payment_method_id: string;
}

export interface OkResponse {
  ok: boolean;
}

// ----------------------------------------------------------------------------
// Invoices & Charges
// ----------------------------------------------------------------------------

export interface InvoiceLine {
  description: string;
  quantity: string;
  unit_price: string | null;
  amount: string;
  line_type: string | null;
}

/** One capture attempt against an invoice. */
export interface ChargeAttempt {
  charge_id: string;
  status: string;
  amount: string;
  refunded_amount: string | null;
  cancellation_reason: string | null;
  cancellation_party: string | null;
  confirmation_url: string | null;
  created_at: string | null;
}

// ----------------------------------------------------------------------------
// Type Guards
// ----------------------------------------------------------------------------

export interface Invoice {
  id: string;
  number: number;
  status: string;
  reason: string | null;
  subtotal: string;
  total: string;
  currency: string;
  period_start: string | null;
  period_end: string | null;
  created_at: string | null;
  paid_at: string | null;
  lines: InvoiceLine[] | null;
  charges: ChargeAttempt[] | null;
}

export interface InvoiceListResponse {
  invoices: Invoice[];
  next_cursor: number | null;
}

export interface PayInvoiceResponse {
  confirmation_url: string;
  invoice_id: string;
  charge_id: string;
  amount: string;
}

export interface ReactivateResponse {
  confirmation_url: string;
  invoice_id: string;
  charge_id: string;
  amount: string;
}

export interface ChargeStatus {
  charge_id: string;
  status: string;
  cancellation_party: string | null;
  cancellation_reason: string | null;
  invoice_id: string;
  applied: boolean;
}

// ----------------------------------------------------------------------------
// Subscription lifecycle
// ----------------------------------------------------------------------------

export interface CancelSubscriptionRequest {
  reason_code: string;
  reason_text?: string | null;
}

export interface CancelSubscriptionResponse {
  canceled: boolean;
  cancel_at_period_end: boolean;
  access_until: string | null;
  message: string | null;
}

export interface ResumeSubscriptionResponse {
  resumed: boolean;
  cancel_at_period_end: boolean;
  access_until: string | null;
}

// ----------------------------------------------------------------------------
// Billing account (реквизиты плательщика, ФЛ/ЮЛ)
// ----------------------------------------------------------------------------

export type BillingAccountKind = "individual" | "legal_entity";

export interface BillingAccount {
  tenant_id: string;
  kind: string;
  email: string | null;
  phone: string | null;
  display_name: string | null;
  inn: string | null;
  kpp: string | null;
  legal_address: string | null;
}

export interface BillingAccountPatch {
  kind?: string | null;
  email?: string | null;
  phone?: string | null;
  display_name?: string | null;
  inn?: string | null;
  kpp?: string | null;
  legal_address?: string | null;
}

// ----------------------------------------------------------------------------
// LLM credit packages
// ----------------------------------------------------------------------------

export interface LlmCreditPurchaseRequest {
  package_count: number;
  return_url?: string | null;
}

export interface PurchaseResponse {
  requires_payment: boolean;
  confirmation_url: string;
  invoice_id: string;
  charge_id: string;
  amount: string;
  usd_cents_pending: number;
}

export interface RefundRequestCreate {
  reason_code: string;
  comment?: string | null;
}

// ----------------------------------------------------------------------------
// Refund requests — aggregate status only; the execution channel never
// leaves the control plane.
// ----------------------------------------------------------------------------

export interface RefundRequestView {
  request_id: string;
  number: number;
  status: string;
  amount_kop: number;
  created_at: string;
}

export interface RefundRequestListResponse {
  requests: RefundRequestView[];
}

// ----------------------------------------------------------------------------
// Cancellation reasons (the survey in CancelSubscriptionModal)
// ----------------------------------------------------------------------------

export type CancelReason =
  | "too_expensive"
  | "missing_features"
  | "switched_service"
  | "not_using"
  | "technical_issues"
  | "temporary_pause"
  | "other";

/**
 * Check if the response indicates an active subscription.
 * Returns true only if the data is BillingInformation with a non-null status.
 */
export function hasActiveSubscription(
  data: BillingInformation | SubscriptionStatus
): data is BillingInformation {
  // SubscriptionStatus (bare { subscribed: boolean }) is never BillingInformation
  if ("subscribed" in data) {
    return false;
  }
  return data.status !== null;
}

/**
 * Check if the response indicates an active *paid* subscription.
 * Returns true only for status === "active" (excludes trialing, past_due, etc.).
 */
export function hasPaidSubscription(
  data: BillingInformation | SubscriptionStatus
): data is BillingInformation {
  if ("subscribed" in data) {
    return false;
  }
  return data.status === BillingStatus.ACTIVE;
}

/**
 * Check if a license is valid and active.
 */
export function isLicenseValid(license: LicenseStatus): boolean {
  return license.has_license && license.status === "active";
}

// Occupied seat count from the unified predicate.
// The frontend reads this instead of computing usedSeats + pendingSeats
// locally, so UI and server agree.
export interface SeatOccupancyResponse {
  occupied_seats: number;
}
