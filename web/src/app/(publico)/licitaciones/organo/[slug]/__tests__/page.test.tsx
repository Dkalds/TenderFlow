import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

/**
 * Hub público por órgano (F6.5). Se fija lo que la página promete y no su
 * maquetación: el nombre sale del backend (nunca se adivina desde el slug), el
 * listado se filtra por ese slug, y un órgano sin hub es un 404 sin pedir el
 * listado — contenido delgado no se publica.
 */
vi.mock("@/lib/publico-api", () => ({ obtenerHubs: vi.fn(), listarLicitaciones: vi.fn() }));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));
vi.mock("@vercel/analytics", () => ({ track: vi.fn() }));

const { obtenerHubs, listarLicitaciones } = await import("@/lib/publico-api");
const { default: HubOrgano, generateMetadata } = await import("../page");

const HUBS = {
  ccaa: [],
  cpv: [],
  organo: [{ slug: "consejeria-de-sanidad", nombre: "Consejería de Sanidad", total: 14 }],
};

function pedir(slug: string, p?: string) {
  return {
    params: Promise.resolve({ slug }),
    searchParams: Promise.resolve(p ? { p } : {}),
  };
}

describe("HubOrgano", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(obtenerHubs).mockResolvedValue(HUBS);
    vi.mocked(listarLicitaciones).mockResolvedValue({
      items: [{ ref: "r1", titulo: "Mantenimiento del sistema de citas", fuente: "placsp", ccaa: "Madrid" }],
      total: 14,
    } as Awaited<ReturnType<typeof listarLicitaciones>>);
  });

  it("titula con el nombre que da el backend y filtra el listado por el slug", async () => {
    render(await HubOrgano(pedir("consejeria-de-sanidad")));

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Licitaciones de Consejería de Sanidad",
    );
    expect(listarLicitaciones).toHaveBeenCalledWith(
      expect.objectContaining({ organo: "consejeria-de-sanidad", offset: 0 }),
    );
  });

  it("un órgano sin hub es un 404 y no pide el listado", async () => {
    await expect(HubOrgano(pedir("organo-inexistente"))).rejects.toThrow("NEXT_NOT_FOUND");
    expect(listarLicitaciones).not.toHaveBeenCalled();
  });

  it("un slug malformado es un 404 sin preguntar a la API", async () => {
    await expect(HubOrgano(pedir("Con Espacios"))).rejects.toThrow("NEXT_NOT_FOUND");
    expect(obtenerHubs).not.toHaveBeenCalled();
  });

  it("el canonical es auto-referente e incluye la página", async () => {
    const meta = await generateMetadata(pedir("consejeria-de-sanidad", "2"));
    expect(meta.alternates?.canonical).toBe("/licitaciones/organo/consejeria-de-sanidad?p=2");
  });
});
