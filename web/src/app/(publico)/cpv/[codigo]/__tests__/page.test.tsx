import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

/**
 * Hub por código CPV, que sirven dos rutas: la página 1 (`cpv/[codigo]`) y la
 * interna a la que el proxy reescribe `?p=N` (`hub-paginado/cpv/[codigo]/[pagina]`).
 * Ninguna lee la query, que es lo que las deja en la caché ISR (ver
 * `lib/paginacion-hubs.ts`). Se fija que cada página sigue diciendo y enlazando
 * lo mismo que cuando leía `?p=`, y que un código malformado sigue siendo un 404
 * sin llamada de red.
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
const paginada = await import("@/app/(publico)/hub-paginado/cpv/[codigo]/[pagina]/page");

function pedir(codigo: string) {
  return { params: Promise.resolve({ codigo }) };
}

function pedirPagina(codigo: string, pagina: string) {
  return { params: Promise.resolve({ codigo, pagina }) };
}

/** Un listado de `total` anuncios, del que la API devuelve una fila. */
function listado(total: number) {
  return {
    items: [{ ref: "r1", titulo: "Licencias de software de gestión", fuente: "placsp", ccaa: "Aragón" }],
    total,
  } as Awaited<ReturnType<typeof listarLicitaciones>>;
}

describe("HubCpv", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listarLicitaciones).mockResolvedValue(listado(160));
  });

  it("la página 1 pide el primer tramo del prefijo y titula con el código", async () => {
    render(await primera.default(pedir("72")));

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Licitaciones CPV 72");
    expect(listarLicitaciones).toHaveBeenCalledWith({ cpv: "72", limit: 50, offset: 0 });
    expect(screen.getByRole("link", { name: "Siguiente" })).toHaveAttribute("href", "/cpv/72?p=2");
  });

  it("la página 4 es la última: pide su tramo y solo enlaza hacia atrás", async () => {
    render(await paginada.default(pedirPagina("72", "4")));

    expect(listarLicitaciones).toHaveBeenCalledWith({ cpv: "72", limit: 50, offset: 150 });
    const anterior = screen.getByRole("link", { name: "Anterior" });
    expect(anterior).toHaveAttribute("href", "/cpv/72?p=3");
    expect(anterior).toHaveAttribute("rel", "prev");
    expect(screen.queryByRole("link", { name: "Siguiente" })).not.toBeInTheDocument();
  });

  it("los canonicals son auto-referentes y en su forma pública", async () => {
    await expect(primera.generateMetadata(pedir("72222300"))).resolves.toMatchObject({
      alternates: { canonical: "/cpv/72222300" },
    });
    await expect(paginada.generateMetadata(pedirPagina("72222300", "2"))).resolves.toMatchObject({
      alternates: { canonical: "/cpv/72222300?p=2" },
      openGraph: { url: "/cpv/72222300" },
    });
  });

  it("un código malformado es un 404 sin llamada de red, en las dos rutas", async () => {
    await expect(primera.default(pedir("abc"))).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(paginada.default(pedirPagina("abc", "2"))).rejects.toThrow("NEXT_NOT_FOUND");
    expect(listarLicitaciones).not.toHaveBeenCalled();
  });

  it("una página más allá de la última es un 404, como antes", async () => {
    vi.mocked(listarLicitaciones).mockResolvedValue({ items: [], total: 160 });
    await expect(paginada.default(pedirPagina("72", "5"))).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it.each(["1", "01", "-3", "abc"])("un segmento %j, que el proxy nunca escribe, es un 404", async (pagina) => {
    await expect(paginada.default(pedirPagina("72", pagina))).rejects.toThrow("NEXT_NOT_FOUND");
    expect(listarLicitaciones).not.toHaveBeenCalled();
  });

  it("ninguna de las dos rutas se genera en el build y ambas se revalidan cada hora", async () => {
    expect(await primera.generateStaticParams()).toEqual([]);
    expect(await paginada.generateStaticParams()).toEqual([]);
    expect(primera.revalidate).toBe(3600);
    expect(paginada.revalidate).toBe(3600);
  });
});
