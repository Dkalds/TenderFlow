import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

/**
 * Hub público por órgano (F6.5). Se fija lo que la página promete y no su
 * maquetación: el nombre sale del backend (nunca se adivina desde el slug), el
 * listado se filtra por ese slug, y un órgano sin hub es un 404 sin pedir el
 * listado — contenido delgado no se publica.
 *
 * Lo sirven dos rutas: la página 1 y la interna a la que el proxy reescribe
 * `?p=N`, que recibe el número por `params` (ver `lib/paginacion-hubs.ts`).
 * Las dos tienen que dar la misma página que daba antes la query.
 */
vi.mock("@/lib/publico-api", () => ({ obtenerHubs: vi.fn(), listarLicitaciones: vi.fn() }));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));
vi.mock("@vercel/analytics", () => ({ track: vi.fn() }));

const { obtenerHubs, listarLicitaciones } = await import("@/lib/publico-api");
const primera = await import("../page");
const paginada = await import("@/app/(publico)/hub-paginado/licitaciones/organo/[slug]/[pagina]/page");

const HUBS = {
  ccaa: [],
  cpv: [],
  organo: [{ slug: "consejeria-de-sanidad", nombre: "Consejería de Sanidad", total: 14 }],
};

function pedir(slug: string) {
  return { params: Promise.resolve({ slug }) };
}

function pedirPagina(slug: string, pagina: string) {
  return { params: Promise.resolve({ slug, pagina }) };
}

/** Un listado de `total` anuncios, del que la API devuelve una fila. */
function listado(total: number) {
  return {
    items: [{ ref: "r1", titulo: "Mantenimiento del sistema de citas", fuente: "placsp", ccaa: "Madrid" }],
    total,
  } as Awaited<ReturnType<typeof listarLicitaciones>>;
}

describe("HubOrgano", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(obtenerHubs).mockResolvedValue(HUBS);
    vi.mocked(listarLicitaciones).mockResolvedValue(listado(14));
  });

  it("titula con el nombre que da el backend y filtra el listado por el slug", async () => {
    render(await primera.default(pedir("consejeria-de-sanidad")));

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Licitaciones de Consejería de Sanidad");
    expect(listarLicitaciones).toHaveBeenCalledWith(
      expect.objectContaining({ organo: "consejeria-de-sanidad", offset: 0 }),
    );
  });

  it("un órgano sin hub es un 404 y no pide el listado", async () => {
    await expect(primera.default(pedir("organo-inexistente"))).rejects.toThrow("NEXT_NOT_FOUND");
    expect(listarLicitaciones).not.toHaveBeenCalled();
  });

  it("un slug malformado es un 404 sin preguntar a la API", async () => {
    await expect(primera.default(pedir("Con Espacios"))).rejects.toThrow("NEXT_NOT_FOUND");
    expect(obtenerHubs).not.toHaveBeenCalled();
  });

  it("el canonical de la página 1 es el hub sin query", async () => {
    const meta = await primera.generateMetadata(pedir("consejeria-de-sanidad"));
    expect(meta.alternates?.canonical).toBe("/licitaciones/organo/consejeria-de-sanidad");
  });

  it("el canonical de la página interna es la URL pública, con ?p=", async () => {
    // La página se sirve desde `/hub-paginado/…/2`, pero esa ruta no existe
    // para nadie: lo que se declara es la URL que se indexa.
    const meta = await paginada.generateMetadata(pedirPagina("consejeria-de-sanidad", "2"));
    expect(meta.alternates?.canonical).toBe("/licitaciones/organo/consejeria-de-sanidad?p=2");
    expect(meta.openGraph?.url).toBe("/licitaciones/organo/consejeria-de-sanidad");
  });

  it("la página 2 pide su tramo y enlaza a la 1 sin ?p y a la 3 con él", async () => {
    vi.mocked(listarLicitaciones).mockResolvedValue(listado(140));
    render(await paginada.default(pedirPagina("consejeria-de-sanidad", "2")));

    expect(listarLicitaciones).toHaveBeenCalledWith(
      expect.objectContaining({ organo: "consejeria-de-sanidad", offset: 50, limit: 50 }),
    );
    const anterior = screen.getByRole("link", { name: "Anterior" });
    expect(anterior).toHaveAttribute("href", "/licitaciones/organo/consejeria-de-sanidad");
    expect(anterior).toHaveAttribute("rel", "prev");
    const siguiente = screen.getByRole("link", { name: "Siguiente" });
    expect(siguiente).toHaveAttribute("href", "/licitaciones/organo/consejeria-de-sanidad?p=3");
    expect(siguiente).toHaveAttribute("rel", "next");
    expect(screen.getByRole("link", { current: "page" })).toHaveTextContent("2");
  });

  it("una página más allá de la última es un 404, como antes", async () => {
    vi.mocked(listarLicitaciones).mockResolvedValue({ items: [], total: 14 });
    await expect(paginada.default(pedirPagina("consejeria-de-sanidad", "9"))).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it.each(["1", "0", "02", "abc", "1e+21"])(
    "un segmento %j, que el proxy nunca escribe, es un 404 sin preguntar a la API",
    async (pagina) => {
      await expect(paginada.default(pedirPagina("consejeria-de-sanidad", pagina))).rejects.toThrow("NEXT_NOT_FOUND");
      await expect(paginada.generateMetadata(pedirPagina("consejeria-de-sanidad", pagina))).rejects.toThrow(
        "NEXT_NOT_FOUND",
      );
      expect(obtenerHubs).not.toHaveBeenCalled();
      expect(listarLicitaciones).not.toHaveBeenCalled();
    },
  );

  it("ninguna de las dos rutas se genera en el build y ambas se revalidan cada hora", async () => {
    // Con la lista vacía cada página se genera y se cachea en su primera
    // visita; sin la función, la ruta se renderizaba en cada petición.
    expect(await primera.generateStaticParams()).toEqual([]);
    expect(await paginada.generateStaticParams()).toEqual([]);
    expect(primera.revalidate).toBe(3600);
    expect(paginada.revalidate).toBe(3600);
  });
});
