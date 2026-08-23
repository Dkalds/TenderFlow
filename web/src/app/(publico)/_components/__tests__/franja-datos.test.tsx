import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

/**
 * Lo que estos tests fijan es la honestidad de la franja, no su maquetación.
 *
 * Dos riesgos concretos: que enseñe ceros cuando la API no responde —el build
 * de CI se hace sin backend, y un «0 expedientes publicables» en portada es
 * peor que no enseñar nada—, y que alguien sustituya el dato del backend por un
 * recuento del cliente, que es justo lo que ADR-014 prohíbe.
 */
vi.mock("@/lib/publico-api", () => ({
  contarPublicables: vi.fn(),
  obtenerHubs: vi.fn(),
}));

const { contarPublicables, obtenerHubs } = await import("@/lib/publico-api");
const { FranjaDatos } = await import("../franja-datos");

function conDatos(total: number, ccaa: number, cpv: number) {
  vi.mocked(contarPublicables).mockResolvedValue(total);
  vi.mocked(obtenerHubs).mockResolvedValue({
    ccaa: Array.from({ length: ccaa }, (_, i) => ({ slug: `c${i}`, nombre: `CCAA ${i}`, total: 10 })),
    cpv: Array.from({ length: cpv }, (_, i) => ({ codigo: `${i}`, nombre: `CPV ${i}`, total: 10 })),
  } as Awaited<ReturnType<typeof obtenerHubs>>);
}

describe("FranjaDatos", () => {
  beforeEach(() => vi.clearAllMocks());

  it("muestra las tres cifras que devuelve la API, formateadas en es-ES", async () => {
    conDatos(12345, 17, 42);

    render(await FranjaDatos());

    expect(screen.getByText("12.345")).toBeInTheDocument();
    expect(screen.getByText("17")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("no renderiza nada si la API no da total", async () => {
    conDatos(0, 17, 42);

    expect(await FranjaDatos()).toBeNull();
  });

  it("no renderiza nada si no hay hubs que citar", async () => {
    conDatos(12345, 0, 0);

    expect(await FranjaDatos()).toBeNull();
  });

  it("cuenta las listas tal cual llegan, sin filtrarlas ni derivarlas", async () => {
    // El backend ya aplica su umbral por hub: si el frontend recontara o
    // filtrara, el número dejaría de ser el que la API afirma.
    conDatos(500, 3, 7);

    render(await FranjaDatos());

    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
  });
});
