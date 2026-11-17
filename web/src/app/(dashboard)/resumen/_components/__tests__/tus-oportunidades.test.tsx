import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type { PursuitMetrics } from "@/lib/api-types";

/**
 * «Tus oportunidades» pinta el reparto por fase que publica `/pursuits/metrics`
 * (`oportunidades_por_estado`) sin contar oportunidades en el navegador, y la previsión del
 * trimestre en curso, no la última clave del mapa.
 */

const metricsState: { data?: PursuitMetrics; isPending: boolean; error: unknown; refetch: () => void } = {
  data: undefined,
  isPending: false,
  error: null,
  refetch: vi.fn(),
};
vi.mock("@/hooks/use-pursuits", () => ({ usePursuitMetrics: () => metricsState }));

import { filasDeFase, trimestreDe, TusOportunidades } from "../tus-oportunidades";

const HOY = new Date(2026, 10, 16, 10, 0);

function estado(estado: string, n: number, proximo_cierre: string | null = null) {
  return { estado, n, proximo_cierre } as NonNullable<PursuitMetrics["oportunidades_por_estado"]>[number];
}

const POR_ESTADO = [
  estado("identified", 1, "2026-12-18"),
  estado("qualifying", 3, "2026-11-30"),
  estado("go_no_go", 0),
  estado("preparing", 0),
  estado("submitted", 0),
  estado("won", 1),
  estado("lost", 1),
  estado("withdrawn", 15),
];

describe("filasDeFase", () => {
  it("da las seis fases del tablero y suma las tres cerradas con su reparto", () => {
    const filas = filasDeFase(POR_ESTADO, HOY);
    expect(filas.map((fila) => `${fila.titulo}:${fila.n}`)).toEqual([
      "Identificada:1",
      "En cualificación:3",
      "Decisión:0",
      "Preparando oferta:0",
      "Presentada:0",
      "Cerradas:17",
    ]);
    expect(filas[5].detalle).toBe("1 ganada · 1 perdida · 15 retiradas");
  });

  it("dice cuándo cierra la primera, en singular o como próximo cierre", () => {
    const filas = filasDeFase(POR_ESTADO, HOY);
    expect(filas[0].detalle).toBe("cierra en 32 d");
    expect(filas[1].detalle).toBe("próximo cierre en 14 d");
    expect(filas[2].detalle).toBeNull();
  });

});

describe("TusOportunidades", () => {
  beforeEach(() => {
    metricsState.isPending = false;
    metricsState.error = null;
    metricsState.data = {
      organization_id: 1,
      pursuits_identified: 21,
      pursuits_submitted: 2,
      pursuits_won: 1,
      pursuits_lost: 1,
      perdidas_n_minimo: 5,
      pipeline_sin_importe: 0,
      unidad_de_conteo: "oportunidad",
      pipeline_value_eur: 3_300_000,
      awarded_amount_eur: 1_300_000,
      prevision_trimestral: { [trimestreDe(new Date())]: 2_700_000, "2099-Q1": 9_000_000 },
      oportunidades_por_estado: POR_ESTADO,
    };
  });

  it("pinta las fases con su recuento y un cuadro por oportunidad", () => {
    render(<TusOportunidades />);
    const fases = within(screen.getByRole("list", { name: "Oportunidades por fase" })).getAllByRole("listitem");
    expect(fases).toHaveLength(6);
    expect(fases[5]).toHaveTextContent("Cerradas");
    expect(fases[5]).toHaveTextContent("17");
    expect(screen.getByRole("link", { name: "Abrir el tablero" })).toHaveAttribute("href", "/oportunidades");
  });

  it("la previsión es la del trimestre en curso, no la última del mapa", () => {
    render(<TusOportunidades />);
    const celda = screen.getByText("Previsión trimestre").closest('[data-slot="stat-cell"]') as HTMLElement;
    expect(celda).toHaveTextContent("2,7 M");
    expect(celda).not.toHaveTextContent("9 M");
  });

  it("con una API sin el reparto no pinta fases a cero: no se sabe, no es que no haya", () => {
    metricsState.data = { ...metricsState.data!, oportunidades_por_estado: undefined };
    render(<TusOportunidades />);
    expect(screen.queryByRole("list", { name: "Oportunidades por fase" })).toBeNull();
    expect(screen.getByText("Valor del pipeline")).toBeInTheDocument();
  });

  it("sin previsión para este trimestre lo dice en vez de pintar un cero", () => {
    metricsState.data = { ...metricsState.data!, prevision_trimestral: {} };
    render(<TusOportunidades />);
    expect(screen.getByText("nada con fecha este trimestre")).toBeInTheDocument();
  });
});
