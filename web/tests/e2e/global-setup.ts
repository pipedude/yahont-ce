import { FullConfig, request } from "@playwright/test";
import {
  TEST_ADMIN_CREDENTIALS,
  TEST_ADMIN2_CREDENTIALS,
  WORKER_USER_POOL_SIZE,
  workerUserCredentials,
} from "@tests/e2e/constants";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  putMockLlmDefaultScript,
  waitForMockLlmServer,
} from "@tests/e2e/utils/mockLlm";

const PREFLIGHT_TIMEOUT_MS = 60_000;
const PREFLIGHT_POLL_INTERVAL_MS = 2_000;
const PREFLIGHT_WARN_AFTER_MS = 15_000;

/**
 * Poll the health endpoint until the server is ready or we time out.
 * Fails fast with a clear error so developers don't see cryptic browser errors.
 */
async function waitForServer(baseURL: string): Promise<void> {
  const healthURL = baseURL;
  const deadline = Date.now() + PREFLIGHT_TIMEOUT_MS;
  const startTime = Date.now();
  let warned = false;

  console.log(`[global-setup] Waiting for server at ${healthURL} ...`);

  while (Date.now() < deadline) {
    try {
      const res = await fetch(healthURL);
      if (res.ok) {
        // The web root answers before the API does: nginx serves the
        // frontend while api_server is still migrating, and /api/* returns
        // 502. Waiting only for the root let the register/login calls fail
        // on a freshly restarted stack (stand, 2026-09-19).
        const apiRes = await fetch(`${healthURL}/api/settings`);
        if (apiRes.status !== 502) {
          console.log("[global-setup] Server is ready.");
          return;
        }
        console.log(
          "[global-setup] The web root is up, the API is still 502, retrying ..."
        );
      } else {
        console.log(
          `[global-setup] Server returned ${res.status}, retrying ...`
        );
      }
    } catch {
      // Connection refused / DNS error — server not up yet.
    }

    if (!warned && Date.now() - startTime >= PREFLIGHT_WARN_AFTER_MS) {
      warned = true;
      console.warn(
        `[global-setup] ⚠ Still waiting for server after ${
          PREFLIGHT_WARN_AFTER_MS / 1000
        }s.\n` +
          `  Please verify that both the backend and frontend are running.\n` +
          `  You can start them with: ods compose dev`
      );
    }

    await new Promise((r) => setTimeout(r, PREFLIGHT_POLL_INTERVAL_MS));
  }

  throw new Error(
    `Onyx is not running at ${baseURL}. ` +
      `Timed out after ${
        PREFLIGHT_TIMEOUT_MS / 1000
      }s waiting for ${healthURL} to return 200. ` +
      `Make sure the backend and frontend are running (e.g. \`ods compose dev\`).`
  );
}

/**
 * Register a user via the backend API. Idempotent — silently succeeds if the
 * user already exists (HTTP 400 with "REGISTER_USER_ALREADY_EXISTS").
 */
async function ensureUserExists(
  apiBase: string,
  email: string,
  password: string
): Promise<void> {
  const ctx = await request.newContext({ baseURL: apiBase });
  try {
    const res = await ctx.post("/api/auth/register", {
      data: { email, username: email, password },
    });

    if (res.ok()) {
      console.log(`[global-setup] Registered user ${email}`);
    } else {
      const body = await res.text();
      // "REGISTER_USER_ALREADY_EXISTS" is the standard FastAPI-Users error code
      if (
        res.status() === 400 &&
        body.includes("REGISTER_USER_ALREADY_EXISTS")
      ) {
        console.log(`[global-setup] User ${email} already exists, skipping.`);
      } else {
        console.warn(
          `[global-setup] Unexpected response registering ${email}: ${res.status()} ${body}`
        );
      }
    }
  } finally {
    await ctx.dispose();
  }
}

/**
 * Log in via the API and save the resulting cookies as a Playwright storage
 * state file.  No browser is needed — this uses Playwright's lightweight
 * request context, which is much faster and produces no console noise.
 */
async function apiLoginAndSaveState(
  baseURL: string,
  email: string,
  password: string,
  storageStatePath: string
): Promise<void> {
  const ctx = await request.newContext({ baseURL });
  try {
    const res = await ctx.post("/api/auth/login", {
      form: { username: email, password },
    });
    if (!res.ok()) {
      const body = await res.text();
      throw new Error(
        `[global-setup] Login failed for ${email}: ${res.status()} ${body}`
      );
    }
    await ctx.storageState({ path: storageStatePath });
  } finally {
    await ctx.dispose();
  }
}

/**
 * Pin the test user's language to English. The ru locale is the app default
 * now, but the whole suite asserts English UI strings; PATCH /user/language
 * writes both the stored preference and the NEXT_LOCALE cookie, so the state
 * file must be re-saved afterwards to capture the cookie.
 */
async function setLanguage(
  baseURL: string,
  storageStatePath: string,
  language: "en" | "ru" = "en"
): Promise<void> {
  const ctx = await request.newContext({
    baseURL,
    storageState: storageStatePath,
  });
  try {
    const res = await ctx.patch("/api/user/language", {
      data: { language },
    });
    if (res.ok()) {
      await ctx.storageState({ path: storageStatePath });
    } else {
      console.warn(
        `[global-setup] Failed to set language for ${storageStatePath}: ${res.status()}`
      );
    }
  } finally {
    await ctx.dispose();
  }
}

/**
 * Set the user's display name via the personalization API. This dismisses the
 * first-time "What should Onyx call you?" prompt that otherwise covers the
 * chat UI and silently breaks tests that interact with the action popover.
 */
async function setDisplayName(
  baseURL: string,
  storageStatePath: string,
  name: string
): Promise<void> {
  const ctx = await request.newContext({
    baseURL,
    storageState: storageStatePath,
  });
  try {
    const res = await ctx.patch("/api/user/personalization", {
      data: { name },
    });
    if (!res.ok()) {
      console.warn(
        `[global-setup] Failed to set display name for ${storageStatePath}: ${res.status()}`
      );
    }
  } finally {
    await ctx.dispose();
  }
}

/**
 * Promote a user to admin by adding them to the Admin default group.
 * Promote a user to admin via the manage API.
 * Requires an authenticated context (admin storage state).
 */
async function promoteToAdmin(
  baseURL: string,
  adminStorageState: string,
  email: string
): Promise<void> {
  const ctx = await request.newContext({
    baseURL,
    storageState: adminStorageState,
  });
  try {
    const groupsRes = await ctx.get(
      "/api/manage/admin/user-group?include_default=true"
    );
    if (!groupsRes.ok()) {
      const body = await groupsRes.text();
      throw new Error(
        `[global-setup] Cannot fetch user groups — the primary admin account ` +
          `(${TEST_ADMIN_CREDENTIALS.email}) may not have admin privileges ` +
          `(status ${groupsRes.status()}).\n\n` +
          `This usually happens when running tests against a non-fresh database ` +
          `where another user was registered first.\n\n` +
          `To fix this, reset to a seeded database: ods db restore --fetch-seeded\n` +
          `Response body: ${body}`
      );
    }
    const groups = (await groupsRes.json()) as Array<{
      id: number;
      name: string;
      is_default?: boolean;
    }>;
    const adminGroup = groups.find(
      (g) => g.is_default === true && g.name === "Admin"
    );
    if (!adminGroup) {
      throw new Error(
        `[global-setup] Admin default group not found in response: ${JSON.stringify(
          groups.map((g) => ({
            id: g.id,
            name: g.name,
            is_default: g.is_default,
          }))
        )}`
      );
    }

    const usersRes = await ctx.get("/api/manage/users/accepted/all");
    if (!usersRes.ok()) {
      const body = await usersRes.text();
      throw new Error(
        `[global-setup] Failed to list users (status ${usersRes.status()}): ${body}`
      );
    }
    const users = (await usersRes.json()) as Array<{
      id: string;
      email: string;
    }>;
    const target = users.find(
      (u) => u.email.toLowerCase() === email.toLowerCase()
    );
    if (!target) {
      // A multitenant stand provisions a NEW tenant per registration
      // (get_or_provision_tenant), so a user registered here cannot appear
      // in the admin's tenant. The signature: the tenant holds the E2E
      // ADMIN and NONE of the other E2E users. Warn and continue — the
      // specs that need admin2 must be run with pre-invited users. A
      // single-tenant stack keeps the hard failure: there the workers ARE in
      // the tenant, so a missing admin2 is a real error.
      const adminEmail = TEST_ADMIN_CREDENTIALS.email.toLowerCase();
      const anyOtherE2eUser = users.some((u) => {
        const other = u.email.toLowerCase();
        return (
          other.endsWith("@example.com") &&
          other !== email.toLowerCase() &&
          other !== adminEmail
        );
      });
      if (!anyOtherE2eUser) {
        console.warn(
          `[global-setup] User ${email} not found in the admin's tenant — ` +
            `skipping the Admin promotion (multitenant stand: every ` +
            `registration provisions its own tenant; pre-invite the E2E ` +
            `users into the target tenant)`
        );
        return;
      }
      throw new Error(
        `[global-setup] User ${email} not found — cannot add to Admin group`
      );
    }

    const res = await ctx.post(
      `/api/manage/admin/user-group/${adminGroup.id}/add-users`,
      { data: { user_ids: [target.id] } }
    );
    if (res.ok()) {
      console.log(`[global-setup] Added ${email} to Admin group`);
    } else {
      const body = await res.text();
      console.warn(
        `[global-setup] Failed to add ${email} to Admin group: ${res.status()} ${body}`
      );
    }
  } finally {
    await ctx.dispose();
  }
}

async function globalSetup(config: FullConfig) {
  // Get baseURL from config, fallback to localhost:3000
  const baseURL = config.projects[0]?.use?.baseURL || "http://localhost:3000";

  // ── Preflight check ──────────────────────────────────────────────────
  await waitForServer(baseURL);

  // ── Provision test users via API ─────────────────────────────────────
  // The first user registered becomes the admin automatically.
  // Order matters: admin first, then admin2, then worker users.
  await ensureUserExists(
    baseURL,
    TEST_ADMIN_CREDENTIALS.email,
    TEST_ADMIN_CREDENTIALS.password
  );
  await ensureUserExists(
    baseURL,
    TEST_ADMIN2_CREDENTIALS.email,
    TEST_ADMIN2_CREDENTIALS.password
  );

  for (let i = 0; i < WORKER_USER_POOL_SIZE; i++) {
    const { email, password } = workerUserCredentials(i);
    await ensureUserExists(baseURL, email, password);
  }

  // ── Login via API and save storage state ───────────────────────────
  await apiLoginAndSaveState(
    baseURL,
    TEST_ADMIN_CREDENTIALS.email,
    TEST_ADMIN_CREDENTIALS.password,
    "admin_auth.json"
  );

  await setDisplayName(baseURL, "admin_auth.json", "Admin");
  await setLanguage(baseURL, "admin_auth.json");

  // Promote admin2 now that we have an admin session
  await promoteToAdmin(
    baseURL,
    "admin_auth.json",
    TEST_ADMIN2_CREDENTIALS.email
  );

  await apiLoginAndSaveState(
    baseURL,
    TEST_ADMIN2_CREDENTIALS.email,
    TEST_ADMIN2_CREDENTIALS.password,
    "admin2_auth.json"
  );
  await setDisplayName(baseURL, "admin2_auth.json", "Admin 2");
  await setLanguage(baseURL, "admin2_auth.json");

  for (let i = 0; i < WORKER_USER_POOL_SIZE; i++) {
    const { email, password } = workerUserCredentials(i);
    const storageStatePath = `worker${i}_auth.json`;
    await apiLoginAndSaveState(baseURL, email, password, storageStatePath);
    await setDisplayName(baseURL, storageStatePath, "worker");
    await setLanguage(baseURL, storageStatePath);
  }

  // ── Register the mock LLM script and make its provider the default ─
  // Many tests depend on a default LLM being configured (file uploads,
  // assistant creation, etc.).  Re-use the admin session we just saved.
  await waitForMockLlmServer();
  await putMockLlmDefaultScript();
  const adminCtx = await request.newContext({
    baseURL,
    storageState: "admin_auth.json",
  });
  try {
    const client = new OnyxApiClient(adminCtx, baseURL);
    await client.ensurePublicProvider();
  } finally {
    await adminCtx.dispose();
  }
}

export default globalSetup;
