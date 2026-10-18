/**
 * Billing action functions for mutations.
 *
 * The cloud billing surface is the unified /api/admin/billing proxy: reads
 * hit the 5-minute cached billing-information, mutations invalidate the SWR
 * tree.
 *
 * License actions stay self-hosted only: /api/license/*, including
 * /api/license/downgrade (Community tier).
 */

import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import type { ErrorResponseBody } from "@/lib/fetcher";
import {
  BindingResponse,
  BillingAccount,
  BillingAccountPatch,
  CancelSubscriptionRequest,
  CancelSubscriptionResponse,
  ChargeStatus,
  CommunityDowngradeResponse,
  CreateCheckoutSessionRequest,
  CreateCheckoutSessionResponse,
  Invoice,
  InvoiceListResponse,
  PayInvoiceResponse,
  ReactivateResponse,
  LlmCreditPurchaseRequest,
  OkResponse,
  PaymentMethodListResponse,
  PlanChangeRequest,
  PlanUpdateRequest,
  PlanUpdateResponse,
  ProrationPreview,
  PurchaseResponse,
  RefundRequestCreate,
  RefundRequestListResponse,
  RefundRequestView,
  ResumeSubscriptionResponse,
  SeatUpdateRequest,
  SeatUpdateResponse,
} from "@/lib/billing/types";
import { PlanCatalog } from "@/lib/billing/plan-catalog";

function getBillingBaseUrl(): string {
  // Unified: the cloud proxy and the self-hosted billing API share one
  // prefix, so the frontend has a single base URL.
  return "/api/admin/billing";
}

async function billingRead<T>(endpoint: string): Promise<T> {
  const response = await fetch(`${getBillingBaseUrl()}${endpoint}`);
  return finishBillingResponse<T>(response);
}

/** Every JSON body the billing endpoints below accept. */
type BillingRequestBody =
  | CreateCheckoutSessionRequest
  | SeatUpdateRequest
  | PlanChangeRequest
  | PlanUpdateRequest
  | CancelSubscriptionRequest
  | BillingAccountPatch
  | LlmCreditPurchaseRequest
  | RefundRequestCreate
  | { return_url: string }
  | { return_url: string; method_type: string };

async function billingSend<T>(
  endpoint: string,
  method: "POST" | "PATCH" | "DELETE",
  body?: BillingRequestBody
): Promise<T> {
  const response = await fetch(`${getBillingBaseUrl()}${endpoint}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  return finishBillingResponse<T>(response);
}

/** A billing API failure that keeps the HTTP status: the callers branch
 * on specific answers (409 on a stale seat count, 402 on a decline). */
export class BillingApiError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "BillingApiError";
    this.status = status;
  }
}

async function finishBillingResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error: ErrorResponseBody = await response.json().catch(() => ({}));
    throw new BillingApiError(
      response.status,
      error.detail || "Billing request failed"
    );
  }
  return response.json();
}

const billingPost = <T>(endpoint: string, body?: BillingRequestBody) =>
  billingSend<T>(endpoint, "POST", body);

const billingGet = billingRead;

const billingPatch = <T>(endpoint: string, body?: BillingRequestBody) =>
  billingSend<T>(endpoint, "PATCH", body);

const billingDelete = <T>(endpoint: string) =>
  billingSend<T>(endpoint, "DELETE");

// ── Checkout & seats ─────────────────────────────────────────────────────

export const createCheckoutSession = (request?: CreateCheckoutSessionRequest) =>
  billingPost<CreateCheckoutSessionResponse>(
    "/create-checkout-session",
    request
  );

export const updateSeatCount = (request: SeatUpdateRequest) =>
  billingPost<SeatUpdateResponse>("/seats/update", request);

/** `unpaid` → paid re-entry, full period from the payment date. Called by
 * the gated page and the Manage Plan unpaid banner. */
export const reactivateSubscription = (returnUrl: string) =>
  billingPost<ReactivateResponse>("/subscription/reactivate", {
    return_url: returnUrl,
  });

// ── Manage Plan (control plane via the proxy) ───────────────────────────

export const getPlanCatalog = () => billingGet<PlanCatalog>("/plans");

export const previewPlanChange = (request: PlanChangeRequest) =>
  billingPost<ProrationPreview>("/plan/preview", request);

export const updatePlan = (request: PlanUpdateRequest) =>
  billingPost<PlanUpdateResponse>("/plan/update", request);

export const listPaymentMethods = () =>
  billingGet<PaymentMethodListResponse>("/payment-methods");

/** The only binding without a charge. `methodType` is one of the types
 * ЮKassa binds without a payment: bank_card, sbp. */
export const startPaymentMethodBinding = (
  returnUrl: string,
  methodType: string
) =>
  billingPost<BindingResponse>("/payment-methods/binding", {
    return_url: returnUrl,
    method_type: methodType,
  });

export const deletePaymentMethod = (pmId: string) =>
  billingSend<OkResponse>(`/payment-methods/${pmId}`, "DELETE");

export const listInvoices = (cursor?: number) =>
  billingGet<InvoiceListResponse>(
    cursor == null ? "/invoices" : `/invoices?cursor=${cursor}`
  );

export const getInvoice = (invoiceId: string) =>
  billingGet<Invoice>(`/invoices/${invoiceId}`);

export const payInvoice = (invoiceId: string, returnUrl: string) =>
  billingPost<PayInvoiceResponse>(`/invoices/${invoiceId}/pay`, {
    return_url: returnUrl,
  });

export const getChargeStatus = (chargeId: string) =>
  billingGet<ChargeStatus>(`/charges/${chargeId}/status`);

export const cancelSubscription = (request: CancelSubscriptionRequest) =>
  billingPost<CancelSubscriptionResponse>("/subscription/cancel", request);

export const resumeSubscription = () =>
  billingPost<ResumeSubscriptionResponse>("/subscription/resume");

export const getBillingAccount = () =>
  billingGet<BillingAccount>("/billing-account");

export const updateBillingAccount = (patch: BillingAccountPatch) =>
  billingPatch<BillingAccount>("/billing-account", patch);

export const purchaseLlmCredits = (request: LlmCreditPurchaseRequest) =>
  billingPost<PurchaseResponse>("/llm-credits/purchase", request);

export const createRefundRequest = (request: RefundRequestCreate) =>
  billingPost<RefundRequestView>("/refund-requests", request);

export const listRefundRequests = () =>
  billingGet<RefundRequestListResponse>("/refund-requests");

// Comfortably past the backend's own 30s timeout on its control-plane call.
// The cache writes behind these handlers have no socket timeout, so an
// unreachable cache would pin the spinner.
const LICENSE_REQUEST_TIMEOUT_MS: number = 60_000;

// The downgrade rewrites every restricted connector's documents in one request.
// Five minutes is the default read timeout of the Docker Compose nginx, the
// shortest of the bundled proxies. The Helm nginx waits 900 seconds.
const DOWNGRADE_REQUEST_TIMEOUT_MS: number = 5 * 60_000;

// Self-hosted only actions
async function selfHostedPost<T>(
  endpoint: string,
  timeoutMs: number = LICENSE_REQUEST_TIMEOUT_MS
): Promise<T> {
  if (NEXT_PUBLIC_CLOUD_ENABLED) {
    throw new Error(`${endpoint} is only available for self-hosted`);
  }

  let response: Response;
  try {
    response = await fetch(`/api/license${endpoint}`, {
      method: "POST",
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new Error("License request timed out. Please try again.");
    }
    throw error;
  }

  if (!response.ok) {
    const error: ErrorResponseBody = await response.json().catch(() => ({}));
    throw new Error(error.detail || "License request failed");
  }

  return response.json();
}

/**
 * Claim a license from the control plane (self-hosted only).
 *
 * Two modes:
 * - With sessionId: After checkout, exchange session_id for license
 * - Without sessionId: Re-claim using existing license for auth
 */
export const claimLicense = (sessionId?: string) =>
  selfHostedPost<{ success: boolean; license?: unknown }>(
    sessionId ? `/claim?session_id=${encodeURIComponent(sessionId)}` : "/claim"
  );

/**
 * Refresh the cached license data (self-hosted only).
 * Forces a re-read of the license and updates the cache.
 */
export const refreshLicenseCache = () =>
  selfHostedPost<{ success: boolean; message?: string }>("/refresh");

/** Drop this deployment to the Community tier (self-hosted only). */
export const downgradeToCommunity = () =>
  selfHostedPost<CommunityDowngradeResponse>(
    "/downgrade",
    DOWNGRADE_REQUEST_TIMEOUT_MS
  );

/**
 * Upload a license key string (self-hosted only).
 * Used for air-gapped deployments where users paste license keys manually.
 */
export async function uploadLicense(
  licenseKey: string
): Promise<{ success: boolean; message?: string }> {
  if (NEXT_PUBLIC_CLOUD_ENABLED) {
    throw new Error("License upload is only available for self-hosted");
  }

  // Create a file from the license key string
  const blob = new Blob([licenseKey], { type: "text/plain" });
  const formData = new FormData();
  formData.append("license_file", blob, "license.txt");

  const response = await fetch("/api/license/upload", {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const error: ErrorResponseBody = await response.json().catch(() => ({}));
    throw new Error(error.detail || "License upload failed");
  }

  return response.json();
}
