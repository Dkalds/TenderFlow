import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, hydrate } from "@tanstack/react-query";

/**
 * Lo que fija este suite es el contrato de `lib/server-prefetch.ts`:
 *
 * - reenvía la cookie de la request a la API y no pide nada sin ella;
 * - lo que falla no se hidrata (el cliente lo pedirá como antes);
 * - cada consulta lleva un presupuesto de tiempo, y es corto;
 * - no se deshidrata nada pendiente: las pantallas usan `useQuery`;
 * - `transformar` se aplica antes de cachear, igual que el `queryFn` del hook.
 */

const cabeceras = vi.hoisted(() => ({ actual: new Headers() }));
vi.mock("next/headers", () => ({ headers: async () => cabeceras.actual }));

import {
  CABECERA_SECRETO_ORIGEN,
  PRESUPUESTO_PREFETCH_MS,
  cabecerasHaciaApi,
  prefetchEnServidor,
} from "@/lib/server-prefetch";

function respuesta(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function cacheDe(estado: Awaited<ReturnType<typeof prefetchEnServidor>>): QueryClient {
  const client = new QueryClient();
  hydrate(client, estado);
  return client;
}

beforeEach(() => {
  cabeceras.actual = new Headers({ cookie: "session=abc; csrf_token=xyz" });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("prefetchEnServidor", () => {
  it("pide cada consulta al backend con la cookie de la request y la deja hidratable", async () => {
    vi.stubEnv("API_BASE_URL", "https://api.example.test");
    const fetchMock = vi.fn().mockResolvedValue(respuesta({ total: 3 }));
    vi.stubGlobal("fetch", fetchMock);

    const estado = await prefetchEnServidor([
      { queryKey: ["analytics", "overview"], path: "/api/v1/analytics/overview?q=erp" },
    ]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.example.test/api/v1/analytics/overview?q=erp");
    expect((init.headers as Record<string, string>).cookie).toBe("session=abc; csrf_token=xyz");
    expect(init.cache).toBe("no-store");
    expect(init.signal).toBeInstanceOf(AbortSignal);
    expect(cacheDe(estado).getQueryData(["analytics", "overview"])).toEqual({ total: 3 });
  });

  it("aplica `transformar` antes de cachear", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respuesta({ ids: ["a", "b"] })));

    const estado = await prefetchEnServidor([
      {
        queryKey: ["radar", "dismissals"],
        path: "/api/v1/radar/dismissals",
        transformar: (cuerpo) => (cuerpo as { ids: string[] }).ids,
      },
    ]);

    expect(cacheDe(estado).getQueryData(["radar", "dismissals"])).toEqual(["a", "b"]);
  });

  it("una consulta que falla no se hidrata y no tumba a las demás", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) =>
        Promise.resolve(url.includes("/roto") ? respuesta({ detail: "boom" }, 503) : respuesta({ ok: 1 })),
      ),
    );

    const estado = await prefetchEnServidor([
      { queryKey: ["roto"], path: "/api/v1/roto" },
      { queryKey: ["sano"], path: "/api/v1/sano" },
    ]);

    const client = cacheDe(estado);
    expect(client.getQueryData(["sano"])).toEqual({ ok: 1 });
    expect(client.getQueryState(["roto"])).toBeUndefined();
  });

  it("un error de red (o el presupuesto agotado) tampoco rompe el render", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("timeout", "TimeoutError")));

    const estado = await prefetchEnServidor([{ queryKey: ["lenta"], path: "/api/v1/lenta" }]);

    expect(estado.queries).toEqual([]);
  });

  it("sin cookie no pide nada: una petición anónima sólo devolvería 401", async () => {
    cabeceras.actual = new Headers();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const estado = await prefetchEnServidor([{ queryKey: ["x"], path: "/api/v1/x" }]);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(estado.queries).toEqual([]);
  });

  it("el presupuesto es corto: el render lo espera y el cliente sabe pedir el dato solo", () => {
    // Con las funciones en `fra1`, junto a la API, una consulta sana cabe de
    // sobra. Subirlo vuelve a retener el HTML entero por una API lenta o fría.
    expect(PRESUPUESTO_PREFETCH_MS).toBeLessThanOrEqual(600);
  });

  it("espera a sus consultas: no deshidrata ninguna pendiente", async () => {
    // Una promesa deshidratada se resolvería al hidratar y `useQuery` pintaría
    // el dato donde el HTML del servidor pintó el esqueleto.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => new Promise((resolver) => setTimeout(() => resolver(respuesta({ ok: 1 })), 20))),
    );

    const estado = await prefetchEnServidor([{ queryKey: ["lenta"], path: "/api/v1/lenta" }]);

    expect(estado.queries).toHaveLength(1);
    expect(estado.queries[0].state.status).toBe("success");
    expect(estado.queries[0]).not.toHaveProperty("promise");
  });

  it("la petición lleva la señal del presupuesto", async () => {
    // `AbortSignal.timeout` usa temporizadores nativos que los fake timers no
    // mueven; se comprueba que la señal que viaja es la del presupuesto.
    const senal = new AbortController().signal;
    const timeout = vi.spyOn(AbortSignal, "timeout").mockReturnValue(senal);
    try {
      const fetchMock = vi.fn().mockResolvedValue(respuesta({}));
      vi.stubGlobal("fetch", fetchMock);
      await prefetchEnServidor([{ queryKey: ["x"], path: "/api/v1/x" }]);
      expect(timeout).toHaveBeenCalledWith(PRESUPUESTO_PREFETCH_MS);
      expect((fetchMock.mock.calls[0][1] as RequestInit).signal).toBe(senal);
    } finally {
      timeout.mockRestore();
    }
  });
});

/**
 * Opción B del RFC 2026-10-24: con el secreto de origen, la API cuenta estas
 * llamadas por la IP del visitante y no por la del servidor de Next.
 */
describe("secreto de origen hacia la API", () => {
  function cabecerasEnviadas(fetchMock: ReturnType<typeof vi.fn>): Record<string, string> {
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    return init.headers as Record<string, string>;
  }

  it("con API_ORIGIN_SECRET manda el secreto y el x-real-ip de la request", async () => {
    vi.stubEnv("API_ORIGIN_SECRET", "s".repeat(64));
    cabeceras.actual = new Headers({ cookie: "session=abc", "x-real-ip": "81.33.120.45" });
    const fetchMock = vi.fn().mockResolvedValue(respuesta({ ok: 1 }));
    vi.stubGlobal("fetch", fetchMock);

    await prefetchEnServidor([{ queryKey: ["a"], path: "/api/v1/a" }]);

    const enviadas = cabecerasEnviadas(fetchMock);
    expect(enviadas[CABECERA_SECRETO_ORIGEN]).toBe("s".repeat(64));
    expect(enviadas["x-real-ip"]).toBe("81.33.120.45");
    expect(CABECERA_SECRETO_ORIGEN).toBe("x-tf-origin-secret");
  });

  it("sin la variable no manda ni el secreto ni la IP", async () => {
    vi.stubEnv("API_ORIGIN_SECRET", "");
    cabeceras.actual = new Headers({ cookie: "session=abc", "x-real-ip": "81.33.120.45" });
    const fetchMock = vi.fn().mockResolvedValue(respuesta({ ok: 1 }));
    vi.stubGlobal("fetch", fetchMock);

    await prefetchEnServidor([{ queryKey: ["a"], path: "/api/v1/a" }]);

    const enviadas = cabecerasEnviadas(fetchMock);
    expect(enviadas).not.toHaveProperty(CABECERA_SECRETO_ORIGEN);
    expect(enviadas).not.toHaveProperty("x-real-ip");
  });

  it("no reenvía cabeceras de la request que no sean la cookie y la IP", () => {
    vi.stubEnv("API_ORIGIN_SECRET", "s".repeat(64));
    const entrantes = new Headers({
      cookie: "session=abc",
      [CABECERA_SECRETO_ORIGEN]: "falso", // pragma: allowlist secret -- valor de prueba
      "x-forwarded-for": "6.6.6.6",
    });
    const enviadas = cabecerasHaciaApi("session=abc", entrantes);
    expect(enviadas[CABECERA_SECRETO_ORIGEN]).toBe("s".repeat(64));
    expect(enviadas).not.toHaveProperty("x-forwarded-for");
    expect(enviadas).not.toHaveProperty("x-real-ip");
  });
});
