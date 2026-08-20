/**
 * Lo que la ola 1 de la migración necesita que `apiGet` cumpla.
 *
 * No es un test del hook sino del transporte que ahora comparten: el cliente
 * tipado no tenía un solo call site, así que nada comprobaba que funcionara de
 * verdad. Dos cosas lo rompían en silencio y ambas están fijadas aquí:
 *
 *  1. `openapi-fetch` construye `new Request(url)`; con la `baseUrl` vacía que
 *     había, la URL quedaba relativa y `Request` la rechaza fuera del navegador.
 *  2. El cliente captura `globalThis.fetch` al crearse, así que un doble
 *     instalado después nunca llegaba a usarse.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiGet } from "@/lib/api-client";
import { callCredentials, callMethod, callUrl, jsonResponse } from "./fetch-call";

/** Una respuesta nueva por llamada: el cuerpo de `Response` solo se lee una vez. */
function stub(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(body, status)));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiGet", () => {
  it("usa el fetch global vigente en el momento de la llamada", async () => {
    const fetchMock = stub({ last_extraction: "2026-08-17T00:00:00Z" });

    const data = await apiGet("/api/v1/meta/last-extraction");

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(data.last_extraction).toBe("2026-08-17T00:00:00Z");
  });

  it("pide la ruta del esquema con la cookie de sesión", async () => {
    const fetchMock = stub({ ids: [] });

    await apiGet("/api/v1/radar/dismissals");

    const call = fetchMock.mock.calls[0];
    expect(callUrl(call)).toBe("/api/v1/radar/dismissals");
    expect(callMethod(call)).toBe("GET");
    expect(callCredentials(call)).toBe("include");
  });

  it("serializa la query y descarta los parámetros sin valor", async () => {
    // Es lo que sustituye al `if (x) params.set(...)` de cada hook: un filtro
    // vacío no debe acotar la consulta.
    const fetchMock = stub({ opportunities: [] });

    await apiGet("/api/v1/analytics/scoring", {
      params: { query: { limit: 24, exclude_dismissed: true, tecnologia: undefined } },
    });

    const url = callUrl(fetchMock.mock.calls[0]);
    expect(url).toContain("limit=24");
    expect(url).toContain("exclude_dismissed=true");
    expect(url).not.toContain("tecnologia");
  });

  it("sin query no añade interrogante a la URL", async () => {
    const fetchMock = stub({ items: [] });

    await apiGet("/api/v1/watchlist/items", { params: { query: { organization_id: null } } });

    expect(callUrl(fetchMock.mock.calls[0])).toBe("/api/v1/watchlist/items");
  });

  it("convierte un error HTTP en ApiError con su status y su detalle", async () => {
    stub({ detail: "Sin permiso" }, 403);

    await expect(apiGet("/api/v1/webhooks/event-types")).rejects.toMatchObject({
      status: 403,
      message: "Sin permiso",
    });
    await expect(apiGet("/api/v1/webhooks/event-types")).rejects.toBeInstanceOf(ApiError);
  });
});
