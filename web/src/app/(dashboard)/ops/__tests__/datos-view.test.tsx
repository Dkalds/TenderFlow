import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * Ops › Datos: lo que se mide del dato, una vez.
 *
 * La vista abría con cuatro cifras de las que dos nunca se medían («Cobertura
 * de NIF» y «de módulo SAP», siempre «sin medir») y las otras dos se repetían
 * más abajo y en la tira de salud; la cola de errores salía por cuarta vez.
 */

// Los bloques que traen su propia consulta y su propio test no se montan aquí.
vi.mock("@/components/source-freshness-panel", () => ({ SourceFreshnessPanel: () => null }));
vi.mock("@/components/calibracion-baja", () => ({ CalibracionBajaBlock: () => null }));
vi.mock("@/components/charts/calidad-datos-charts", () => ({
  CalidadCompletenessChart: () => <p>gráfico de completitud</p>,
  CalidadTendenciaChart: () => <p>gráfico de tendencia</p>,
}));

import CalidadDatosView from "../_components/calidad-datos-view";

const CALIDAD = {
  total_records: 713000,
  pct_cpv: 91,
  pct_importe: 80,
  pct_fecha: 99,
  pct_titulo: 100,
  cobertura_nif: null,
  cobertura_modulo_sap: null,
  dlq_count: 6,
  pct_fecha_iso: 100,
  fechas_no_iso: 0,
  last_scrape_hours_ago: 4,
  reportes_por_tipo: {},
  tendencia_completitud: [],
};

function montar(calidad: unknown = CALIDAD, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((...call: unknown[]) =>
      Promise.resolve(
        callUrl(call).startsWith("/api/v1/analytics/quality")
          ? jsonResponse(calidad, status)
          : jsonResponse({}),
      ),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <CalidadDatosView />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Ops › Datos", () => {
  it("no enseña coberturas que el backend nunca mide", async () => {
    montar();

    await screen.findByText("Completitud por columna");
    expect(screen.queryByText("Cobertura de NIF")).not.toBeInTheDocument();
    expect(screen.queryByText("Cobertura de módulo SAP")).not.toBeInTheDocument();
  });

  it("no repite lo que ya dice la tira de salud", async () => {
    montar();

    await screen.findByText("Completitud por columna");
    expect(screen.queryByText(/Cola de errores/)).not.toBeInTheDocument();
    expect(screen.queryByText("Frescura de la ingesta")).not.toBeInTheDocument();
    expect(screen.queryByText("Resumen de la ingesta")).not.toBeInTheDocument();
  });

  it("dice una vez sobre cuántos registros van los porcentajes", async () => {
    montar();

    expect(await screen.findByText(/sobre 713\.000 registros/)).toBeInTheDocument();
    expect(screen.queryByText("Registros totales")).not.toBeInTheDocument();
  });

  it("con la consulta caída dice que falló y no pinta paneles a cero", async () => {
    montar({ detail: "boom" }, 500);

    expect(await screen.findByText("No se pudieron cargar las métricas de calidad")).toBeInTheDocument();
    expect(screen.queryByText("Completitud por columna")).not.toBeInTheDocument();
  });
});
