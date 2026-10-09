import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

function fuente(source: string, extra: Record<string, unknown> = {}) {
  return {
    source,
    status: "success",
    last_success_at: "2026-07-30T09:00:00Z",
    last_seen_updated: null,
    cursor_updated_at: null,
    lag_hours: 2,
    detected_within_24h_pct: 97.5,
    sample_size: 40,
    fetched: 10,
    parsed: 10,
    discarded: 0,
    errors: 0,
    is_degraded: false,
    is_backfill: false,
    warning: null,
    ...extra,
  };
}

const TED_CAIDA = fuente("TED", {
  status: "failed",
  last_success_at: null,
  lag_hours: null,
  detected_within_24h_pct: null,
  sample_size: 0,
  errors: 1,
  is_degraded: true,
  warning: "No hay una ingesta exitosa registrada.",
});

const respuesta = vi.hoisted(() => ({ data: undefined as unknown }));

vi.mock("@/hooks/use-source-freshness", () => ({
  useSourceFreshness: () => ({
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: vi.fn(),
    data: respuesta.data,
  }),
}));

import { SourceFreshnessPanel } from "@/components/source-freshness-panel";
import { TooltipProvider } from "@/components/ui/tooltip";

function montar(sources: unknown[], healthy: number, total: number) {
  respuesta.data = {
    healthy_sources: healthy,
    total_sources: total,
    healthy_sources_pct: total ? (healthy / total) * 100 : 0,
    generated_at: "2026-07-30T00:00:00Z",
    sources,
  };
  // El «Actualizar» lleva `Tooltip`, y en la app el proveedor lo pone
  // `components/providers.tsx`: aquí hay que ponerlo a mano.
  render(
    <TooltipProvider>
      <SourceFreshnessPanel />
    </TooltipProvider>,
  );
}

afterEach(cleanup);

describe("SourceFreshnessPanel", () => {
  it("makes a degraded source visible alongside its SLA measurements", () => {
    montar([fuente("PLACSP"), TED_CAIDA], 1, 2);

    expect(screen.getByText(/1 fuente degradada/)).toBeInTheDocument();
    expect(screen.getByText("PLACSP")).toBeInTheDocument();
    expect(screen.getByText("TED")).toBeInTheDocument();
    expect(screen.getByText("97,5%")).toBeInTheDocument();
    expect(screen.getByText("Sin ingesta")).toBeInTheDocument();
  });

  it("los lotes de carga histórica van aparte y no cuentan como fuentes", () => {
    // En producción cuatro `bulk_YYYYMM` (uno fallido, dos sin terminar) dejaban
    // el aviso de «fuentes degradadas» encendido para siempre.
    montar(
      [
        fuente("placsp"),
        fuente("bulk_202607", { status: "failed", last_success_at: null, lag_hours: null, is_backfill: true }),
        fuente("bulk_202608", {
          status: "running",
          is_backfill: true,
          warning: "La fuente sigue marcada como ejecutándose; el proceso pudo quedar interrumpido.",
        }),
        fuente("bulk_202609", { is_backfill: true }),
      ],
      1,
      1,
    );

    expect(screen.getByText("Todas las fuentes activas cumplen el SLA")).toBeInTheDocument();
    expect(screen.queryByText(/degradada/)).not.toBeInTheDocument();

    const vivas = screen.getByRole("table", { name: "Frescura, latencia y cobertura por fuente" });
    expect(within(vivas).getByText("placsp")).toBeInTheDocument();
    expect(within(vivas).queryByText("bulk_202607")).not.toBeInTheDocument();

    const lotes = screen.getByRole("table", { name: "Cargas históricas por mes" });
    expect(within(lotes).getByText("bulk_202607").closest("tr")).toHaveTextContent("Fallida");
    expect(within(lotes).getByText("bulk_202608").closest("tr")).toHaveTextContent("Sin terminar");
    expect(within(lotes).getByText("bulk_202609").closest("tr")).toHaveTextContent("Completada");
  });

  it("sin lotes no pinta la sección de cargas históricas", () => {
    montar([fuente("placsp")], 1, 1);

    expect(screen.queryByText("Cargas históricas")).not.toBeInTheDocument();
  });

  it("solo con lotes no afirma que las fuentes cumplen el SLA", () => {
    // Cero fuentes vivas no es «todas al día»: es que no hay ninguna que medir.
    montar([fuente("bulk_202609", { is_backfill: true })], 0, 0);

    expect(screen.queryByText("Todas las fuentes activas cumplen el SLA")).not.toBeInTheDocument();
    expect(screen.getByText("Aún no hay fuentes con actividad registrada")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Cargas históricas por mes" })).toBeInTheDocument();
  });
});
