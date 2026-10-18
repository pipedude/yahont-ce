"use client";

import { usePathname } from "next/navigation";
import AccessRestrictedPage from "@/components/errorPages/AccessRestrictedPage";
import { ApplicationStatus } from "@/lib/settings/types";

// Paths accessible even when gated - allows users to manage billing updates.
const ALLOWED_GATED_PATHS = ["/admin/billing"];

// Seat-limit remediation needs the users page (remove members/invites to get
// back under the limit) — and only that state keeps the users API reachable:
// the tenant-tracking middleware blocks a GATED_ACCESS tenant's other API
// calls, so the page would render as a broken shell there.
const ALLOWED_SEAT_LIMIT_PATHS = ["/admin/users"];

/**
 * Check if pathname matches an allowed path exactly or is a subpath.
 * Uses strict matching to prevent bypasses like "/admin/billing-foo".
 */
function isPathAllowed(pathname: string, allowedPaths: string[]): boolean {
  return allowedPaths.some(
    (allowedPath) =>
      pathname === allowedPath || pathname.startsWith(allowedPath + "/")
  );
}

export default function GatedContentWrapper({
  status,
  children,
}: {
  status: ApplicationStatus;
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  const allowedPaths =
    status === ApplicationStatus.SEAT_LIMIT_EXCEEDED
      ? [...ALLOWED_GATED_PATHS, ...ALLOWED_SEAT_LIMIT_PATHS]
      : ALLOWED_GATED_PATHS;

  if (isPathAllowed(pathname, allowedPaths)) {
    return <>{children}</>;
  }

  return <AccessRestrictedPage />;
}
