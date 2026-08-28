import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ErrorApiPublica,
  SITEMAP_POR_FICHERO,
  contarPublicables,
  entradasSitemap,
  listarLicitaciones,
  obtenerHubs,
  obtenerLicitacion,
  obtenerResumenPublico,
} from "../publico-api";

const ENTORNO_ORIGINAL = { ...process.env };

function respuestaOk(cuerpo: unknown) {
  return { ok: true, status: 200, json: async () => cuerpo } as Response;
}

/** Un 200 cuyo cuerpo no es JSON: la página de error de un proxy, típicamente. */
function respuestaIlegible() {
  return {
    ok: true,
    status: 200,
    json: async () => {
      throw new SyntaxError("Unexpected token '<'");
    },
  } as unknown as Response;
}

function respuestaCon(status: number) {
  return { ok: false, status } as Response;
}

function urlDeLaLlamada(indice = 0): string {
  return vi.mocked(globalThis.fetch).mock.calls[indice][0] as string;
}

function llamadas(): number {
  return vi.mocked(globalThis.fetch).mock.calls.length;
}

beforeEach(() => {
  process.env.API_BASE_URL = "http://backend:8080";
  delete process.env.NEXT_PHASE;
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

/**
 * El corazón del hallazgo #5: "no existe" y "no pude saberlo" tienen que ser
 * valores distintos, porque con ISR el segundo, leído como el primero,
 * reemplaza en caché una página buena por un 404 indexable.
 */
describe("ausencia confirmada por la API", () => {
  it("un 404 es ausencia: la ficha puede hacer notFound() con fundamento", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaCon(404));

    await expect(obtenerLicitacion("R1")).resolves.toBeNull();
  });

  it("un 410 también: el recurso existió y ya no", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaCon(410));

    await expect(obtenerLicitacion("R1")).resolves.toBeNull();
  });

  it("un 400 es la API diciendo que la petición no vale, no que esté caída", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaCon(400));

    await expect(obtenerLicitacion("??")).resolves.toBeNull();
  });

  it("una ausencia no se reintenta: la respuesta no va a cambiar en 300 ms", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaCon(404));

    await obtenerLicitacion("R1");

    expect(llamadas()).toBe(1);
  });
});

describe("fallo transitorio: lanza en vez de fabricar un 404", () => {
  it("un error de transporte lanza, con estado nulo", async () => {
    vi.mocked(globalThis.fetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const error = await obtenerLicitacion("R1").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ErrorApiPublica);
    expect((error as ErrorApiPublica).estado).toBeNull();
  });

  it("un 500 lanza y conserva el código", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaCon(500));

    const error = await obtenerLicitacion("R1").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ErrorApiPublica);
    expect((error as ErrorApiPublica).estado).toBe(500);
  });

  it("un 503 —Render despertando— lanza igual", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaCon(503));

    await expect(obtenerHubs()).rejects.toBeInstanceOf(ErrorApiPublica);
  });

  it("un 429 lanza pese a ser 4xx: dice 'ahora no', no 'no existe'", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaCon(429));

    await expect(obtenerLicitacion("R1")).rejects.toBeInstanceOf(ErrorApiPublica);
  });

  it("un 200 con cuerpo ilegible es un proxy, no una lista vacía", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaIlegible());

    await expect(obtenerHubs()).rejects.toBeInstanceOf(ErrorApiPublica);
  });

  it("ninguna de las funciones públicas devuelve su reserva ante un fallo", async () => {
    vi.mocked(globalThis.fetch).mockRejectedValue(new Error("ECONNREFUSED"));

    await expect(obtenerLicitacion("R1")).rejects.toBeInstanceOf(ErrorApiPublica);
    await expect(listarLicitaciones({})).rejects.toBeInstanceOf(ErrorApiPublica);
    await expect(obtenerHubs()).rejects.toBeInstanceOf(ErrorApiPublica);
    await expect(obtenerResumenPublico()).rejects.toBeInstanceOf(ErrorApiPublica);
    await expect(contarPublicables()).rejects.toBeInstanceOf(ErrorApiPublica);
    await expect(entradasSitemap(0, 10)).rejects.toBeInstanceOf(ErrorApiPublica);
  });
});

/**
 * La otra mitad del contrato: un backend que contesta "no hay nada" tiene que
 * poder decirlo sin que se confunda con una caída.
 */
describe("un 200 vacío se distingue de un fallo", () => {
  it("un listado sin resultados devuelve la lista vacía, no lanza", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaOk({ items: [], total: 0 }));

    await expect(listarLicitaciones({ ccaa: "ceuta" })).resolves.toEqual({ items: [], total: 0 });
  });

  it("un corpus sin hubs devuelve listas vacías, no lanza", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaOk({ ccaa: [], cpv: [] }));

    await expect(obtenerHubs()).resolves.toEqual({ ccaa: [], cpv: [] });
  });

  it("un corpus de cero expedientes cuenta cero, no lanza", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaOk({ total: 0 }));

    await expect(contarPublicables()).resolves.toBe(0);
  });

  it("un tramo de sitemap vacío es una lista vacía, no lanza", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaOk([]));

    await expect(entradasSitemap(0, 10)).resolves.toEqual([]);
  });
});

describe("reintento acotado", () => {
  it("un fallo aislado se recupera en el segundo intento", async () => {
    vi.mocked(globalThis.fetch)
      .mockRejectedValueOnce(new Error("socket hang up"))
      .mockResolvedValue(respuestaOk({ ccaa: [{ slug: "galicia", total: 10 }], cpv: [] }));

    await expect(obtenerHubs()).resolves.toEqual({
      ccaa: [{ slug: "galicia", total: 10 }],
      cpv: [],
    });
    expect(llamadas()).toBe(2);
  });

  it("no hay bucle: exactamente dos intentos y se rinde", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(respuestaCon(502));

    await expect(obtenerHubs()).rejects.toBeInstanceOf(ErrorApiPublica);
    expect(llamadas()).toBe(2);
  });
});

/**
 * El job `frontend` de CI compila sin `API_BASE_URL` a propósito. Ahí no hay
 * backend que preguntar ni copia previa que proteger, así que lanzar solo
 * rompería un build comprobatorio.
 */
describe("degradación solo en el build deliberadamente sin backend", () => {
  it("sin API_BASE_URL y en fase de build, devuelve la reserva y avisa", async () => {
    delete process.env.API_BASE_URL;
    process.env.NEXT_PHASE = "phase-production-build";
    const aviso = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.mocked(globalThis.fetch).mockRejectedValue(new Error("ECONNREFUSED"));

    await expect(obtenerHubs()).resolves.toEqual({ ccaa: [], cpv: [] });
    await expect(contarPublicables()).resolves.toBe(0);
    expect(aviso).toHaveBeenCalled();
  });

  it("con API_BASE_URL configurada, el build falla en vez de publicar a ciegas", async () => {
    process.env.NEXT_PHASE = "phase-production-build";
    vi.mocked(globalThis.fetch).mockRejectedValue(new Error("ECONNREFUSED"));

    await expect(contarPublicables()).rejects.toBeInstanceOf(ErrorApiPublica);
  });

  it("fuera del build, la falta de API_BASE_URL no exime de lanzar", async () => {
    delete process.env.API_BASE_URL;
    vi.mocked(globalThis.fetch).mockRejectedValue(new Error("ECONNREFUSED"));

    await expect(contarPublicables()).rejects.toBeInstanceOf(ErrorApiPublica);
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
