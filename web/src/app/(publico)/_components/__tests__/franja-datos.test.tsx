import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

/**
 * Lo que estos tests fijan es la honestidad de la franja, no su maquetación.
 *
 * Tres riesgos concretos: que enseñe ceros cuando la API no responde —el build
 * de CI se hace sin backend, y un «0 expedientes publicables» en portada es
 * peor que no enseñar nada—, que alguien sustituya el dato del backend por un
 * recuento del cliente, que es justo lo que ADR-014 prohíbe, y que la fecha de
 * frescura se rellene cuando el backend no la da: el hueco de esa fecha es
 * exactamente la prueba que la franja existe para aportar.
 */
vi.mock("@/lib/publico-api", () => ({
  obtenerResumenPublico: vi.fn(),
  obtenerHubs: vi.fn(),
}));

const { obtenerResumenPublico, obtenerHubs } = await import("@/lib/publico-api");
const { FranjaDatos } = await import("../franja-datos");

function conDatos(total: number, ccaa: number, cpv: number, actualizado?: string) {
  vi.mocked(obtenerResumenPublico).mockResolvedValue({ total, actualizado });
  vi.mocked(obtenerHubs).mockResolvedValue({
    ccaa: Array.from({ length: ccaa }, (_, i) => ({ slug: `c${i}`, nombre: `CCAA ${i}`, total: 10 })),
    cpv: Array.from({ length: cpv }, (_, i) => ({ codigo: `${i}`, nombre: `CPV ${i}`, total: 10 })),
  } as Awaited<ReturnType<typeof obtenerHubs>>);
}

describe("FranjaDatos", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // El camino degradado avisa por consola a propósito; sin esto el ruido
    // ensucia la salida de los tests que lo ejercitan.
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

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

  it("avisa cuando se degrada, en vez de desaparecer en silencio", async () => {
    conDatos(0, 0, 0);

    await FranjaDatos();

    expect(console.warn).toHaveBeenCalled();
  });

  it("cuenta las listas tal cual llegan, sin filtrarlas ni derivarlas", async () => {
    // El backend ya aplica su umbral por hub: si el frontend recontara o
    // filtrara, el número dejaría de ser el que la API afirma.
    conDatos(500, 3, 7);

    render(await FranjaDatos());

    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("publica la fecha del último expediente con su marca legible por máquina", async () => {
    conDatos(500, 3, 7, "2026-08-14T06:00:00+00:00");

    render(await FranjaDatos());

    const fecha = screen.getByText(/14 ago 2026/);
    expect(fecha).toBeInTheDocument();
    expect(fecha.tagName).toBe("TIME");
    expect(fecha).toHaveAttribute("dateTime", "2026-08-14T06:00:00+00:00");
  });

  it("no inventa fecha si el backend no la da", async () => {
    conDatos(500, 3, 7);

    render(await FranjaDatos());

    expect(screen.queryByText(/Último expediente incorporado/)).not.toBeInTheDocument();
  });
});
