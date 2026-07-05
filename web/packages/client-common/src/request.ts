import z from "zod";

import { default as kyBase, type KyInstance } from "ky";

import {
  ListOrganizationsResponseSchema,
  RefreshTokenResponseSchema,
} from "@shelfalign/schema/dtos/auth";
import { BaseErrorResponse } from "@shelfalign/schema/dtos/base";

import { TokenRefreshError, UnauthorizedError } from "./error";
import { INVALID_DATA, INVALID_JSON, tryJson } from "./parsing";

/** Organization handling mode */
export type OrganizationMode =
  | { type: "none" }
  | { type: "static"; organizationId: string }
  | { type: "dynamic"; userType: "ADMIN" | "LIBRARIAN" };

export interface CreateKyClientOptions {
  /** Base URL for API requests (e.g., import.meta.env.VITE_BASE_URL) */
  baseUrl: string;
  /** Whether to enable token refresh on auth errors. Default: false */
  tokenRefresh?: boolean;
  /** Organization handling mode. Default: { type: 'none' } */
  organization?: OrganizationMode;
  /** Maximum retry count for auth errors. Default: 1 */
  maxRetries?: number;
}

/** Auth error codes that should trigger token refresh */
const TOKEN_REFRESH_ERROR_CODES = [
  "INVALID_TOKEN",
  "TOKEN_EXPIRED",
  "UNAUTHORIZED",
  "MISSING_AUTHORIZATION_HEADER",
  "INVALID_AUTHORIZATION_HEADER",
  "INVALID_ACCESS_TOKEN",
  "MISSING_ORGANIZATION_ID",
] as const;

/** Auth error codes that should immediately require sign-in */
const SIGN_IN_REQUIRED_ERROR_CODES = ["SESSION_NOT_FOUND"] as const;

/** Organization error codes that should trigger organization recovery */
const ORGANIZATION_ERROR_CODES = [
  "UNAUTHORIZED_ORGANIZATION",
  "MISSING_ORGANIZATION_ID",
] as const;

function isRefreshTokenRequest(requestUrl: string, baseUrl: string): boolean {
  const normalizedBaseUrl = baseUrl.endsWith("/")
    ? baseUrl.slice(0, -1)
    : baseUrl;
  const refreshUrl = new URL(`${normalizedBaseUrl}/auth/refresh`);
  const url = new URL(requestUrl);

  return (
    url.origin === refreshUrl.origin && url.pathname === refreshUrl.pathname
  );
}

/**
 * Creates a configured ky HTTP client instance.
 *
 * @example
 * // Basic client
 * const ky = createKyClient({ baseUrl: import.meta.env.VITE_BASE_URL });
 *
 * @example
 * // With token refresh
 * const ky = createKyClient({
 *   baseUrl: import.meta.env.VITE_BASE_URL,
 *   tokenRefresh: true,
 * });
 *
 * @example
 * // With static organization (like backoffice app)
 * const ky = createKyClient({
 *   baseUrl: import.meta.env.VITE_BASE_URL,
 *   tokenRefresh: true,
 *   organization: { type: 'static', organizationId: ADMIN_ORGANIZATION_ID },
 * });
 *
 * @example
 * // With dynamic organization
 * const ky = createKyClient({
 *   baseUrl: import.meta.env.VITE_BASE_URL,
 *   tokenRefresh: true,
 *   organization: { type: 'dynamic', userType: 'LIBRARIAN' },
 *   maxRetries: 2,
 * });
 *
 * Note:
 * - If tokenRefresh is true, this client refreshes tokens and retries the failed request automatically.
 * - Do not call deprecated refreshToken() from QueryCache/MutationCache onError handlers.
 * - Handle SignInRequiredError (UnauthorizedError, TokenRefreshError) at app boundary for redirect/logout flow.
 */
export function createKyClient(options: CreateKyClientOptions): KyInstance {
  const {
    baseUrl,
    tokenRefresh = false,
    organization = { type: "none" },
    maxRetries = 1,
  } = options;

  const ky: KyInstance = kyBase.create({
    throwHttpErrors: false,
    credentials: "include",
    hooks: {
      beforeRequest: [
        async ({ request }) => {
          // Inject access token
          const token = localStorage.getItem("accessToken");
          if (token) {
            request.headers.set("Authorization", `Bearer ${token}`);
          }

          // Handle organization ID
          if (organization.type === "static") {
            request.headers.set(
              "x-organization-id",
              organization.organizationId,
            );
          } else if (organization.type === "dynamic") {
            const organizationId = localStorage.getItem("organization");
            request.headers.set("x-organization-id", organizationId ?? "");
          }
        },
      ],
      ...(tokenRefresh
        ? {
            afterResponse: [
              async ({ request, response }) => {
                if (isRefreshTokenRequest(request.url, baseUrl)) {
                  return response;
                }

                // Get current retry count
                const retryCount = Number(
                  request.headers.get("x-retry-request") ?? "0",
                );

                // Skip retry logic if we've exceeded max retries
                if (!Number.isNaN(retryCount) && retryCount >= maxRetries) {
                  return response;
                }

                // Try to parse as error response
                const responseText = await response.clone().text();
                const responseData = tryJson(
                  responseText,
                  BaseErrorResponse,
                  false,
                );

                if (
                  responseData === INVALID_JSON ||
                  responseData === INVALID_DATA
                ) {
                  return response;
                }

                const errorCode = responseData.error.code;

                // Force sign-in for invalid session states
                if (
                  (SIGN_IN_REQUIRED_ERROR_CODES as readonly string[]).includes(
                    errorCode,
                  )
                ) {
                  localStorage.removeItem("accessToken");
                  throw new UnauthorizedError();
                }

                // Handle organization errors for dynamic mode
                if (
                  organization.type === "dynamic" &&
                  (ORGANIZATION_ERROR_CODES as readonly string[]).includes(
                    errorCode,
                  )
                ) {
                  return handleDynamicOrganizationError(
                    ky,
                    baseUrl,
                    organization.userType,
                    request,
                    response,
                    retryCount,
                  );
                }

                // Handle static organization unauthorized error
                if (
                  organization.type === "static" &&
                  errorCode === "UNAUTHORIZED_ORGANIZATION"
                ) {
                  throw new UnauthorizedError();
                }

                // Handle token refresh errors
                if (
                  (TOKEN_REFRESH_ERROR_CODES as readonly string[]).includes(
                    errorCode,
                  )
                ) {
                  return handleTokenRefresh(ky, baseUrl, request, retryCount);
                }

                return response;
              },
            ],
          }
        : { afterResponse: [] }),
    },
  });

  return ky;
}

// Same-tab single-flight: a concurrent burst of 401s (Suspense fan-out,
// refetchOnWindowFocus, etc.) must share one /auth/refresh call, otherwise
// only the first call wins and the rest hit the backend's already-revoked
// previous refresh token and log the user out.
let inFlightRefresh: Promise<string> | null = null;

const AUTH_REFRESH_LOCK = "shelfalign-auth-refresh";

async function performRefresh(
  ky: KyInstance,
  baseUrl: string,
  staleToken: string | null,
): Promise<string> {
  // Double-check under the lock: another tab may have already refreshed
  // while we waited. If so, use its token instead of spending a second
  // rotation.
  const current = localStorage.getItem("accessToken");
  if (current && current !== staleToken) {
    return current;
  }

  const refreshResponse = await ky.post(`${baseUrl}/auth/refresh`);

  if (!refreshResponse.ok) {
    const refreshText = await refreshResponse.clone().text();
    const refreshError = tryJson(refreshText, BaseErrorResponse, false);

    localStorage.removeItem("accessToken");

    if (
      refreshError !== INVALID_JSON &&
      refreshError !== INVALID_DATA &&
      refreshError.error.code === "REFRESH_TOKEN_MISSING"
    ) {
      throw new UnauthorizedError();
    }

    throw new TokenRefreshError();
  }

  const refreshText = await refreshResponse.text();
  const refreshData = tryJson(refreshText, RefreshTokenResponseSchema);

  if (refreshData === INVALID_DATA || refreshData === INVALID_JSON) {
    localStorage.removeItem("accessToken");
    throw new TokenRefreshError();
  }

  const accessToken = refreshData.data.accessToken;
  localStorage.setItem("accessToken", accessToken);
  return accessToken;
}

async function acquireFreshAccessToken(
  ky: KyInstance,
  baseUrl: string,
  staleToken: string | null,
): Promise<string> {
  if (inFlightRefresh) {
    return inFlightRefresh;
  }

  const run = async () => {
    // Cross-tab single-flight via Web Locks when available. Same rationale
    // as the in-memory latch, but across browser tabs sharing cookies.
    if (typeof navigator !== "undefined" && "locks" in navigator) {
      return navigator.locks.request(AUTH_REFRESH_LOCK, () =>
        performRefresh(ky, baseUrl, staleToken),
      );
    }
    return performRefresh(ky, baseUrl, staleToken);
  };

  inFlightRefresh = run().finally(() => {
    inFlightRefresh = null;
  });

  return inFlightRefresh;
}

async function handleTokenRefresh(
  ky: KyInstance,
  baseUrl: string,
  request: Request,
  retryCount: number,
): Promise<Response> {
  const staleToken =
    request.headers.get("Authorization")?.replace(/^Bearer\s+/i, "") ?? null;
  const accessToken = await acquireFreshAccessToken(ky, baseUrl, staleToken);

  const headers = new Headers(request.headers);
  headers.set("Authorization", `Bearer ${accessToken}`);
  headers.set("x-retry-request", `${retryCount + 1}`);

  return ky(new Request(request, { headers }));
}

async function handleDynamicOrganizationError(
  ky: KyInstance,
  baseUrl: string,
  userType: "ADMIN" | "LIBRARIAN",
  request: Request,
  response: Response,
  retryCount: number,
): Promise<Response> {
  localStorage.removeItem("organization");

  const organizationResponse = await ky.get(`${baseUrl}/auth/organizations`);
  if (!organizationResponse.ok) {
    return response;
  }

  const organizationText = await organizationResponse.text();
  const organizationData = tryJson(
    organizationText,
    ListOrganizationsResponseSchema,
  );

  if (organizationData === INVALID_DATA || organizationData === INVALID_JSON) {
    return response;
  }

  const matchingOrganizations = organizationData.data.filter((org) =>
    org.members.some((member) => member.type === userType),
  );

  if (matchingOrganizations.length === 0) {
    throw new UnauthorizedError();
  }

  const newOrganizationId = matchingOrganizations[0]!.id;
  localStorage.setItem("organization", newOrganizationId);

  // Retry the original request with the new organization ID
  const headers = new Headers(request.headers);
  headers.set("x-organization-id", newOrganizationId);
  headers.set("x-retry-request", `${retryCount + 1}`);

  return ky(new Request(request, { headers }));
}

/**
 * @deprecated Use createKyClient({ tokenRefresh: true }) and handle SignInRequiredError globally.
 */
export async function refreshToken(
  baseUrl: string,
  kyInstance: KyInstance,
): Promise<string> {
  const response = await kyInstance.post(`${baseUrl}/auth/refresh`);

  if (!response.ok) {
    throw new Error("Token refresh failed");
  }

  const text = await response.text();
  const result = tryJson(
    text,
    z.object({
      result: z.literal(true),
      data: z.object({
        accessToken: z.string(),
      }),
    }),
  );

  if (result === INVALID_JSON || result === INVALID_DATA) {
    throw new Error("Invalid refresh response");
  }

  const accessToken = result.data.accessToken;
  localStorage.setItem("accessToken", accessToken);
  return accessToken;
}
