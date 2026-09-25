import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

/**
 * Hub por comunidad autónoma, que sirven dos rutas: la página 1
 * (`licitaciones/[ccaa]`) y la interna a la que el proxy reescribe `?p=N`
 * (`hub-paginado/licitaciones/[ccaa]/[pagina]`). Ninguna lee la query, que es
 * lo que las deja en la caché ISR (ver `lib/paginacion-hubs.ts`); lo que aquí
 * se fija es que, pese al cambio de mecanismo, cada página dice y enlaza lo
 * mismo que cuando se servía leyendo `?p=`: canonical, `rel="prev"`/`"next"` y
 * el tramo que se pide a la API.
 */
vi.mock("@/lib/publico-api", () => ({ listarLicitaciones: vi.fn() }));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));
vi.mock("@vercel/analytics", () => ({ track: vi.fn() }));

const { listarLicitaciones } = await import("@/lib/publico-api");
const primera = await import("../page");
const paginada = await import("@/app/(publico)/hub-paginado/licitaciones/[ccaa]/[pagina]/page");

function pedir(ccaa: string) {
  return { params: Promise.resolve({ ccaa }) };
}

function pedirPagina(ccaa: string, pagina: string) {
  return { params: Promise.resolve({ ccaa, pagina }) };
}

/** Un listado de `total` anuncios, del que la API devuelve una fila. */
function listado(total: number) {
  return {
    items: [{ ref: "r1", titulo: "Soporte de la plataforma de expedientes", fuente: "placsp", ccaa: "Madrid" }],
    total,
  } as Awaited<ReturnType<typeof listarLicitaciones>>;
}

describe("HubCcaa", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listarLicitaciones).mockResolvedValue(listado(120));
  });

  it("la página 1 pide el primer tramo y solo enlaza hacia delante", async () => {
    render(await primera.default(pedir("comunidad-de-madrid")));

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Licitaciones de tecnología en Comunidad de Madrid",
    );
    expect(listarLicitaciones).toHaveBeenCalledWith({ ccaa: "comunidad-de-madrid", limit: 50, offset: 0 });
    expect(screen.queryByRole("link", { name: "Anterior" })).not.toBeInTheDocument();
    const siguiente = screen.getByRole("link", { name: "Siguiente" });
    expect(siguiente).toHaveAttribute("href", "/licitaciones/comunidad-de-madrid?p=2");
    expect(siguiente).toHaveAttribute("rel", "next");
  });

  it("el canonical de la página 1 es el hub sin query", () => {
    return expect(primera.generateMetadata(pedir("comunidad-de-madrid"))).resolves.toMatchObject({
      alternates: { canonical: "/licitaciones/comunidad-de-madrid" },
      openGraph: { url: "/licitaciones/comunidad-de-madrid" },
    });
  });

  it("la página 3 pide su tramo y enlaza a sus vecinas por la URL pública", async () => {
    vi.mocked(listarLicitaciones).mockResolvedValue(listado(250));
    render(await paginada.default(pedirPagina("comunidad-de-madrid", "3")));

    expect(listarLicitaciones).toHaveBeenCalledWith({ ccaa: "comunidad-de-madrid", limit: 50, offset: 100 });
    const anterior = screen.getByRole("link", { name: "Anterior" });
    expect(anterior).toHaveAttribute("href", "/licitaciones/comunidad-de-madrid?p=2");
    expect(anterior).toHaveAttribute("rel", "prev");
    const siguiente = screen.getByRole("link", { name: "Siguiente" });
    expect(siguiente).toHaveAttribute("href", "/licitaciones/comunidad-de-madrid?p=4");
    expect(siguiente).toHaveAttribute("rel", "next");
    expect(screen.getByRole("link", { current: "page" })).toHaveTextContent("3");
    // Ningún enlace de la página delata la ruta interna.
    for (const enlace of screen.getAllByRole("link")) {
      expect(enlace.getAttribute("href") ?? "").not.toContain("hub-paginado");
    }
  });

  it("la página 2 enlaza a la 1 sin ?p=1, que sería contenido duplicado", async () => {
    render(await paginada.default(pedirPagina("comunidad-de-madrid", "2")));

    expect(screen.getByRole("link", { name: "Anterior" })).toHaveAttribute("href", "/licitaciones/comunidad-de-madrid");
  });

  it("el canonical de la página interna es la URL pública, con ?p=", () => {
    return expect(paginada.generateMetadata(pedirPagina("comunidad-de-madrid", "3"))).resolves.toMatchObject({
      alternates: { canonical: "/licitaciones/comunidad-de-madrid?p=3" },
      openGraph: { url: "/licitaciones/comunidad-de-madrid" },
    });
  });

  it("las dos rutas publican los mismos metadatos salvo el canonical", async () => {
    const uno = await primera.generateMetadata(pedir("sin-comunidad"));
    const dos = await paginada.generateMetadata(pedirPagina("sin-comunidad", "2"));
    expect({ ...dos, alternates: undefined }).toEqual({ ...uno, alternates: undefined });
    expect(uno.title).toBe("Licitaciones de tecnología en sin comunidad autónoma asignada");
  });

  it("un hub sin licitaciones, o una página más allá de la última, es un 404", async () => {
    vi.mocked(listarLicitaciones).mockResolvedValue({ items: [], total: 0 });
    await expect(primera.default(pedir("comunidad-que-no-existe"))).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(paginada.default(pedirPagina("comunidad-de-madrid", "40"))).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it.each(["1", "0", "02", "2.5", "abc", "9007199254740993"])(
    "un segmento %j, que el proxy nunca escribe, es un 404 sin preguntar a la API",
    async (pagina) => {
      await expect(paginada.default(pedirPagina("comunidad-de-madrid", pagina))).rejects.toThrow("NEXT_NOT_FOUND");
      await expect(paginada.generateMetadata(pedirPagina("comunidad-de-madrid", pagina))).rejects.toThrow(
        "NEXT_NOT_FOUND",
      );
      expect(listarLicitaciones).not.toHaveBeenCalled();
    },
  );

  it("ninguna de las dos rutas se genera en el build y ambas se revalidan cada hora", async () => {
    expect(await primera.generateStaticParams()).toEqual([]);
    expect(await paginada.generateStaticParams()).toEqual([]);
    expect(primera.revalidate).toBe(3600);
    expect(paginada.revalidate).toBe(3600);
  });
});
