/**
 * Panel de publicaciones del Resumen: recharts (y el redux que trae) no viaja
 * en el First Load de /resumen.
 *
 * Los dos cortes que dibujan con recharts se doblan con una factoría que
 * anota su descarga (`vi.mock` la ejecuta la primera vez que algo importa el
 * módulo). El dato se dobla también: aquí interesa cuándo llega cada gráfico.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const h = vi.hoisted(() => ({
  descargados: new Set<string>(),
  cargando: false,
}));

vi.mock("../alcance", () => ({ useFiltrosIgnorados: () => [] }));
vi.mock("../aviso-alcance", () => ({ AvisoAlcance: () => null }));
vi.mock("../../_hooks/use-publicaciones", () => ({
  usePublicaciones: () => ({
    ventana: "desde el 1 sept 2026",
    serie: [],
    serieTruncada: false,
    histograma: [],
    totalHistograma: 0,
    maxHistograma: 0,
    scatterData: [],
    leyenda: [],
    sinImporte: 0,
    muestreado: false,
    totalVentana: 0,
    cargando: h.cargando,
    error: null,
    refetch: () => undefined,
    acotarADia: () => undefined,
  }),
}));
vi.mock("../publicaciones/ritmo-chart", () => {
  h.descargados.add("ritmo");
  return { RitmoChart: () => <p>gráfico de ritmo</p> };
});
vi.mock("../publicaciones/dispersion-scatter", () => {
  h.descargados.add("dispersion");
  return { DispersionScatter: () => <p>nube de dispersión</p> };
});

import { PublicacionesPanel } from "../publicaciones-panel";

// El primer import dinámico transforma el módulo: con la máquina cargada pasa
// de los 5 s por defecto, así que la espera y el test tienen margen propio.
const DESCARGA = { timeout: 15_000 };

beforeEach(() => {
  h.cargando = false;
});

describe("PublicacionesPanel", { timeout: 30_000 }, () => {
  it("mientras llega la serie, el gráfico del corte por defecto ya se está descargando", async () => {
    h.cargando = true;
    const { container } = render(<PublicacionesPanel />);

    expect(container.querySelector(".tf-shimmer")).toBeInTheDocument();
    await vi.waitFor(() => expect(h.descargados.has("ritmo")).toBe(true), DESCARGA);
  });

  it("con la serie, Ritmo se pinta en cuanto llega su código", async () => {
    render(<PublicacionesPanel />);

    expect(await screen.findByText("gráfico de ritmo", {}, DESCARGA)).toBeInTheDocument();
  });

  it("Dispersión no se descarga hasta elegirla", async () => {
    render(<PublicacionesPanel />);
    expect(h.descargados.has("dispersion")).toBe(false);

    fireEvent.click(screen.getByRole("tab", { name: "Dispersión" }));

    expect(await screen.findByText("nube de dispersión", {}, DESCARGA)).toBeInTheDocument();
    expect(h.descargados.has("dispersion")).toBe(true);
  });

  it("Importes son barras de CSS: se pintan sin esperar a nada", () => {
    render(<PublicacionesPanel />);

    fireEvent.click(screen.getByRole("tab", { name: "Importes" }));

    expect(screen.getByText("Ningún expediente del periodo declara importe.")).toBeInTheDocument();
  });
});
