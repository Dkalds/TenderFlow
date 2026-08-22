import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  SITEMAP_POR_FICHERO,
  contarPublicables,
  entradasSitemap,
  listarLicitaciones,
  obtenerHubs,
  obtenerLicitacion,
} from "../publico-api";

const ENTORNO_ORIGINAL = { ...process.env };

function respuestaOk(cuerpo: unknown) {
  return { ok: true, json: async () => cuerpo } as Response;
}

function urlDeLaLlamada(indice = 0): string {
  return vi.mocked(globalThis.fetch).mock.calls[indice][0] as string;
}

beforeEach(() => {
  process.env.API_BASE_URL = "http://backend:8080";
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  process.env = { ...ENTORNO_ORIGINAL };
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("origen y política de caché", () => {
  it("va al backend directamente, porque los rewrites no aplican al fetch del servidor", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaOk({ ccaa: [], cpv: [] }));

    await obtenerHubs();

    expect(urlDeLaLlamada()).toBe("http://backend:8080/api/v1/publico/hubs");
  });

  it("cae en localhost:8080 si no hay API_BASE_URL", async () => {
    delete process.env.API_BASE_URL;
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaOk({ ccaa: [], cpv: [] }));

    await obtenerHubs();

    expect(urlDeLaLlamada()).toBe("http://localhost:8080/api/v1/publico/hubs");
  });

  it("pide revalidación horaria y JSON", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaOk({ ccaa: [], cpv: [] }));

    await obtenerHubs();

    expect(vi.mocked(globalThis.fetch).mock.calls[0][1]).toEqual({
      next: { revalidate: 3600 },
      headers: { Accept: "application/json" },
    });
  });
});

describe("la API caída no tumba la página", () => {
  it("una excepción de red se traduce a la reserva de cada llamante", async () => {
    vi.mocked(globalThis.fetch).mockRejectedValue(new Error("ECONNREFUSED"));

    await expect(obtenerLicitacion("R1")).resolves.toBeNull();
    await expect(listarLicitaciones({})).resolves.toEqual({ items: [], total: 0 });
    await expect(obtenerHubs()).resolves.toEqual({ ccaa: [], cpv: [] });
    await expect(contarPublicables()).resolves.toBe(0);
    await expect(entradasSitemap(0, 10)).resolves.toEqual([]);
  });

  it("una respuesta no-ok se trata igual que la caída", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue({ ok: false, status: 503 } as Response);

    await expect(obtenerLicitacion("R1")).resolves.toBeNull();
    await expect(contarPublicables()).resolves.toBe(0);
  });
});

describe("obtenerLicitacion", () => {
  it("escapa la referencia antes de meterla en la ruta", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaOk({ ref: "a/b" }));

    await obtenerLicitacion("a/b");

    expect(urlDeLaLlamada()).toBe("http://backend:8080/api/v1/publico/licitaciones/a%2Fb");
  });

  it("devuelve el anuncio cuando existe", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaOk({ ref: "R1", titulo: "Obras" }));

    await expect(obtenerLicitacion("R1")).resolves.toEqual({ ref: "R1", titulo: "Obras" });
  });
});

describe("listarLicitaciones", () => {
  it("aplica los valores por defecto de paginación", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaOk({ items: [], total: 0 }));

    await listarLicitaciones({});

    expect(urlDeLaLlamada()).toContain("limit=50");
    expect(urlDeLaLlamada()).toContain("offset=0");
  });

  it("pasa los filtros y la paginación explícita", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaOk({ items: [], total: 0 }));

    await listarLicitaciones({ ccaa: "galicia", cpv: "72", limit: 10, offset: 20 });

    const query = new URL(urlDeLaLlamada()).searchParams;
    expect(query.get("ccaa")).toBe("galicia");
    expect(query.get("cpv")).toBe("72");
    expect(query.get("limit")).toBe("10");
    expect(query.get("offset")).toBe("20");
  });

  it("omite los filtros vacíos en vez de mandarlos en blanco", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaOk({ items: [], total: 0 }));

    await listarLicitaciones({ ccaa: "", cpv: undefined });

    const query = new URL(urlDeLaLlamada()).searchParams;
    expect(query.has("ccaa")).toBe(false);
    expect(query.has("cpv")).toBe(false);
  });

  it("devuelve el total real, que es lo que necesita la paginación del hub", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      respuestaOk({ items: [{ ref: "R1" }], total: 4321 }),
    );

    await expect(listarLicitaciones({})).resolves.toEqual({
      items: [{ ref: "R1" }],
      total: 4321,
    });
  });
});

describe("sitemap", () => {
  it("parte en tramos de 10.000, por debajo del máximo de Google", async () => {
    expect(SITEMAP_POR_FICHERO).toBe(10_000);
    expect(SITEMAP_POR_FICHERO).toBeLessThan(50_000);
  });

  it("contarPublicables lee el total del resumen", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaOk({ total: 12345 }));

    await expect(contarPublicables()).resolves.toBe(12345);
    expect(urlDeLaLlamada()).toBe("http://backend:8080/api/v1/publico/sitemap/resumen");
  });

  it("entradasSitemap pide el tramo pedido", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaOk([{ ref: "R1" }]));

    await expect(entradasSitemap(20_000, 10_000)).resolves.toEqual([{ ref: "R1" }]);
    expect(urlDeLaLlamada()).toBe(
      "http://backend:8080/api/v1/publico/sitemap/entradas?offset=20000&limit=10000",
    );
  });
});

describe("obtenerHubs", () => {
  it("devuelve las listas del backend tal cual", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      respuestaOk({ ccaa: [{ slug: "galicia", total: 10 }], cpv: [{ codigo: "72", total: 5 }] }),
    );

    await expect(obtenerHubs()).resolves.toEqual({
      ccaa: [{ slug: "galicia", total: 10 }],
      cpv: [{ codigo: "72", total: 5 }],
    });
  });
});
