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
  // fdi-allow:localhost-url — fallback SSR/Node legítimo cuando API_BASE_URL no está set; no es dato renderizado.
  baseUrl: typeof window !== "undefined" ? "" : process.env.API_BASE_URL ?? "http://localhost:8080",
  credentials: "include",
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

/**
 * Lightweight fetch wrapper that uses the same auth pattern as the typed client.
 * Use this for dynamic URLs that can't use the typed openapi-fetch client.
 * 401 handling is done centrally here — no need to duplicate in callers.
 *
 * CSRF: si `options.method` es una mutación (POST/PUT/PATCH/DELETE), se
 * adjunta `X-CSRF-Token` igual que `apiMutate` — hasta 2026-08 cualquier
 * mutación enrutada por aquí viajaba sin token y el backend la rechazaba (o
 * peor: pasaba solo por autenticarse con API key en vez de cookie).
 */
export async function fetchWithAuth<T>(
  url: string,
  options?: RequestInit,
): Promise<T> {
  const method = (options?.method ?? "GET").toUpperCase();
  const isMutation = method !== "GET" && method !== "HEAD";
  const csrf = isMutation ? getCsrfToken() : null;
  const res = await fetch(url, {
    credentials: "include",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      ...(options?.headers ?? {}),
    },
  });

  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") {
      window.location.href = "/login";
    }
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? `API error: ${res.status}`);
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
