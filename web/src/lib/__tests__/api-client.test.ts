/**
 * Tests for web/src/lib/api-client.ts
 *
 * Covers: getCsrfToken, apiMutate, ApiError
 *
 * The module-level `api` export (openapi-fetch client) is not exercised here —
 * those are integration tests. We mock `openapi-fetch` so the module can be
 * imported cleanly without a real API schema.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ---------------------------------------------------------------------------
// Mock openapi-fetch BEFORE importing the module under test.
// The `api` object is created at module level; we stub createClient to return
// a no-op object so the import side-effect doesn't fail.
// ---------------------------------------------------------------------------
vi.mock("openapi-fetch", () => ({
  default: vi.fn(() => ({ use: vi.fn(), eject: vi.fn() })),
}));

// @/generated/api is a type-only import (`import type { paths }`) and is
// completely erased at runtime by esbuild/Vite — no mock needed.

import { getCsrfToken, apiMutate, ApiError, esAborto, fetchWithAuth } from "@/lib/api-client";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockFetch(status: number, body: unknown, ok = status >= 200 && status < 300): ReturnType<typeof vi.fn> {
  const jsonFn = vi.fn().mockResolvedValue(body);
  const fetchMock = vi.fn().mockResolvedValue({
    ok,
    status,
    statusText: status === 401 ? "Unauthorized" : "Error",
    json: jsonFn,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

// ---------------------------------------------------------------------------
// Restore globals after every test
// ---------------------------------------------------------------------------

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// getCsrfToken
// ---------------------------------------------------------------------------

describe("getCsrfToken", () => {
  beforeEach(() => {
    // jsdom starts with document.cookie = "" — reset via defineProperty trick
    Object.defineProperty(document, "cookie", {
      writable: true,
      configurable: true,
      value: "",
    });
  });

  it("returns null when there are no cookies", () => {
    expect(getCsrfToken()).toBeNull();
  });

  it("extracts csrf_token from a single-cookie string", () => {
    Object.defineProperty(document, "cookie", {
      writable: true,
      configurable: true,
      value: "csrf_token=abc123",
    });
    expect(getCsrfToken()).toBe("abc123");
  });

  it("extracts csrf_token from a multi-cookie string", () => {
    Object.defineProperty(document, "cookie", {
      writable: true,
      configurable: true,
      value: "session=xyz; csrf_token=tok456; other=val",
    });
    expect(getCsrfToken()).toBe("tok456");
  });

  it("URL-decodes the csrf_token value", () => {
    Object.defineProperty(document, "cookie", {
      writable: true,
      configurable: true,
      value: "csrf_token=hello%20world",
    });
    expect(getCsrfToken()).toBe("hello world");
  });

  it("returns null when csrf_token is absent but other cookies exist", () => {
    Object.defineProperty(document, "cookie", {
      writable: true,
      configurable: true,
      value: "session=abc; user=daniel",
    });
    expect(getCsrfToken()).toBeNull();
  });

  it("returns null on SSR (document undefined)", () => {
    const originalDocument = globalThis.document;
    // @ts-expect-error – simulate SSR
    delete globalThis.document;
    try {
      expect(getCsrfToken()).toBeNull();
    } finally {
      globalThis.document = originalDocument;
    }
  });
});

// ---------------------------------------------------------------------------
// ApiError
// ---------------------------------------------------------------------------

describe("ApiError", () => {
  it("has name 'ApiError'", () => {
    const err = new ApiError(404, "Not found");
    expect(err.name).toBe("ApiError");
  });

  it("sets the status property", () => {
    const err = new ApiError(422, "Validation error");
    expect(err.status).toBe(422);
  });

  it("sets the message property", () => {
    const err = new ApiError(500, "Server crash");
    expect(err.message).toBe("Server crash");
  });

  it("is an instance of Error", () => {
    const err = new ApiError(400, "Bad request");
    expect(err).toBeInstanceOf(Error);
  });

  it("is an instance of ApiError", () => {
    const err = new ApiError(400, "Bad request");
    expect(err).toBeInstanceOf(ApiError);
  });

  it("can be caught as Error", () => {
    expect(() => {
      throw new ApiError(500, "boom");
    }).toThrow(Error);
  });
});

// ---------------------------------------------------------------------------
// Cancelación (fetchWithAuth + esAborto)
// ---------------------------------------------------------------------------

/**
 * React Query aborta el `signal` de la consulta que se queda sin observadores
 * —la del filtro anterior—. Para que eso libere la API, el `signal` tiene que
 * llegar a `fetch`; y para que no se vea, la cancelación tiene que salir como
 * `AbortError`, nunca normalizada a `ApiError`, que se reintentaría y avisaría.
 */
describe("ApiError — tipo del problem+json", () => {
  it("fetchWithAuth conserva el `type` del cuerpo de error", async () => {
    mockFetch(503, {
      type: "https://licitaciones-sap/errors/query-timeout",
      title: "Query Timeout",
      detail: "La consulta tardó demasiado.",
    });

    const error = (await fetchWithAuth("/api/v1/analytics/overview").catch((e: unknown) => e)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(503);
    expect(error.tipo).toBe("https://licitaciones-sap/errors/query-timeout");
    expect(error.message).toBe("La consulta tardó demasiado.");
  });

  it("apiMutate también lo conserva", async () => {
    mockFetch(503, { type: "https://licitaciones-sap/errors/query-timeout", detail: "x" });

    const error = (await apiMutate("POST", "/api/v1/algo", {}).catch((e: unknown) => e)) as ApiError;

    expect(error.tipo).toBe("https://licitaciones-sap/errors/query-timeout");
  });

  it("sin `type` (o con uno que no es texto) queda sin tipo", async () => {
    mockFetch(500, { detail: "boom", type: 42 });

    const error = (await fetchWithAuth("/api/v1/algo").catch((e: unknown) => e)) as ApiError;

    expect(error.tipo).toBeUndefined();
  });
});

describe("fetchWithAuth — cancelación", () => {
  const abortado = () => new DOMException("The operation was aborted.", "AbortError");

  it("pasa el signal a fetch", async () => {
    const fetchMock = mockFetch(200, { ok: true });
    const controller = new AbortController();

    await fetchWithAuth("/api/v1/algo", { signal: controller.signal });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.signal).toBe(controller.signal);
  });

  it("una petición abortada en vuelo sale como AbortError, no como ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abortado()));

    const error = await fetchWithAuth("/api/v1/algo", { signal: new AbortController().signal }).catch((e) => e);

    expect(esAborto(error)).toBe(true);
    expect(error).not.toBeInstanceOf(ApiError);
  });

  it("si se aborta mientras se lee el cuerpo de un error, gana la cancelación", async () => {
    // El `catch` que rescata el cuerpo de un error se tragaba el AbortError y
    // salía un ApiError(503): transitorio, así que se reintentaba y avisaba.
    const controller = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        json: () => {
          controller.abort();
          return Promise.reject(abortado());
        },
      }),
    );

    const error = await fetchWithAuth("/api/v1/algo", { signal: controller.signal }).catch((e) => e);

    expect(esAborto(error)).toBe(true);
    expect(error).not.toBeInstanceOf(ApiError);
  });

  it("sin cancelación, un error sigue siendo un ApiError con su detalle", async () => {
    mockFetch(503, { detail: "Mantenimiento" }, false);
    await expect(fetchWithAuth("/api/v1/algo", { signal: new AbortController().signal })).rejects.toMatchObject({
      status: 503,
      message: "Mantenimiento",
    });
  });
});

describe("esAborto", () => {
  it("reconoce la cancelación venga como DOMException o como Error", () => {
    expect(esAborto(new DOMException("aborted", "AbortError"))).toBe(true);
    const comoError = new Error("aborted");
    comoError.name = "AbortError";
    expect(esAborto(comoError)).toBe(true);
  });

  it("no confunde con una cancelación los fallos de verdad", () => {
    expect(esAborto(new ApiError(500, "boom"))).toBe(false);
    expect(esAborto(new TypeError("Failed to fetch"))).toBe(false);
    expect(esAborto(null)).toBe(false);
    expect(esAborto("AbortError")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// apiMutate
// ---------------------------------------------------------------------------

describe("apiMutate", () => {
  beforeEach(() => {
    // Clear csrf_token so tests start clean
    Object.defineProperty(document, "cookie", {
      writable: true,
      configurable: true,
      value: "",
    });
  });

  it("calls fetch with the correct method and URL", async () => {
    const fetchMock = mockFetch(200, { id: 1 });
    await apiMutate("POST", "/api/test");
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/test");
    expect(init.method).toBe("POST");
  });

  it("sends Content-Type: application/json header", async () => {
    const fetchMock = mockFetch(200, {});
    await apiMutate("POST", "/api/test");
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("sends credentials: 'include'", async () => {
    const fetchMock = mockFetch(200, {});
    await apiMutate("POST", "/api/test");
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe("include");
  });

  it("JSON-serializes the body when provided", async () => {
    const fetchMock = mockFetch(200, { ok: true });
    await apiMutate("PUT", "/api/resource/1", { name: "test", count: 42 });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBe(JSON.stringify({ name: "test", count: 42 }));
  });

  it("sends undefined body when no body is given", async () => {
    const fetchMock = mockFetch(200, {});
    await apiMutate("DELETE", "/api/resource/1");
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBeUndefined();
  });

  it("includes X-CSRF-Token header when csrf_token cookie is present", async () => {
    Object.defineProperty(document, "cookie", {
      writable: true,
      configurable: true,
      value: "csrf_token=mytoken",
    });
    const fetchMock = mockFetch(200, {});
    await apiMutate("POST", "/api/secure");
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("mytoken");
  });

  it("omits X-CSRF-Token header when no csrf_token cookie", async () => {
    const fetchMock = mockFetch(200, {});
    await apiMutate("POST", "/api/open");
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("returns parsed JSON on successful response", async () => {
    mockFetch(200, { data: [1, 2, 3] });
    const result = await apiMutate<{ data: number[] }>("GET" as never, "/api/data");
    expect(result).toEqual({ data: [1, 2, 3] });
  });

  it("supports all mutation methods: POST, PUT, PATCH, DELETE", async () => {
    for (const method of ["POST", "PUT", "PATCH", "DELETE"] as const) {
      const fetchMock = mockFetch(200, {});
      await apiMutate(method, "/api/x");
      const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(init.method).toBe(method);
    }
  });

  it("throws ApiError on non-ok response (e.g. 400)", async () => {
    mockFetch(400, { detail: "Bad request" }, false);
    await expect(apiMutate("POST", "/api/bad")).rejects.toThrow(ApiError);
  });

  it("ApiError has the correct status code on failure", async () => {
    mockFetch(403, { detail: "Forbidden" }, false);
    await expect(apiMutate("DELETE", "/api/admin")).rejects.toMatchObject({
      status: 403,
      message: "Forbidden",
    });
  });

  it("ApiError uses 'Unknown error' when response has no detail field", async () => {
    mockFetch(500, {}, false);
    await expect(apiMutate("POST", "/api/boom")).rejects.toMatchObject({
      status: 500,
      message: "Unknown error",
    });
  });

  it("ApiError falls back to statusText when json() rejects", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      statusText: "Service Unavailable",
      json: vi.fn().mockRejectedValue(new Error("not json")),
    });
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiMutate("POST", "/api/down")).rejects.toMatchObject({
      status: 503,
      message: "Service Unavailable",
    });
  });

  it("redirects to /login (preserving the deep-link) and throws ApiError on 401", async () => {
    // Mock window.location so we can assert the redirect. pathname/search feed
    // the ?redirect= deep-link that mirrors the Next middleware.
    const locationMock = { href: "", pathname: "/mi-watchlist", search: "" };
    vi.stubGlobal("window", { ...globalThis.window, location: locationMock });

    mockFetch(401, {}, false);

    await expect(apiMutate("GET" as never, "/api/protected")).rejects.toMatchObject({
      status: 401,
      message: "Session expired",
    });

    expect(locationMock.href).toBe(`/login?redirect=${encodeURIComponent("/mi-watchlist")}`);
  });
});
