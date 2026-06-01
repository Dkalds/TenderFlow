/**
 * Typed API client generated from FastAPI's OpenAPI schema.
 *
 * Uses openapi-fetch for type-safe requests.
 * Types are generated via `npm run codegen` from /api/openapi.json.
 *
 * In development, Next.js proxies /api/* to the FastAPI backend (see next.config.ts).
 * In production, same-origin deployment means no proxy is needed.
 */

import createClient from "openapi-fetch";
import type { paths } from "@/generated/api";

/**
 * Base API client — all requests go through this.
 * Cookie-based auth (httpOnly) is handled automatically by the browser.
 */
export const api = createClient<paths>({
  baseUrl: typeof window !== "undefined" ? "" : process.env.API_BASE_URL ?? "http://localhost:8080",
  credentials: "include", // send cookies for session auth
  headers: {
    "Content-Type": "application/json",
  },
});

/**
 * Global middleware: redirect to login on 401 responses.
 * Centralizes auth expiry handling for all API calls via the typed client.
 */
api.use({
  onResponse({ response }) {
    if (response.status === 401 && typeof window !== "undefined") {
      window.location.href = "/login";
    }
    return undefined;
  },
});

/**
 * Helper to get CSRF token from cookie (set by the API on login).
 * Include this in mutation requests (POST/PUT/DELETE).
 */
export function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Fetch wrapper that includes CSRF token for mutations.
 */
export async function apiMutate<T>(
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  url: string,
  body?: unknown,
): Promise<T> {
  const csrf = getCsrfToken();
  const res = await fetch(url, {
    method,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") {
      window.location.href = "/login";
      throw new ApiError(401, "Session expired");
    }
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, error.detail ?? "Unknown error");
  }

  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
