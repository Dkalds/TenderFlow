/**
 * «Mercado por segmento» en Competidores: concentración, reparto, baja de
 * referencia y bajas por grupo, contra el contrato de la API.
 *
 * Lo que se fija: cada bloque pide a su endpoint lo que ese endpoint entiende
 * —`/hhi` sin la barra, la cuota y la referencia por el segmento elegido,
 * `/bajas` con la parte de la barra que aplica—; un corte que la API no
 * desglosa se dice en vez de pintar el mercado entero como si fuera el
 * segmento; y la carga, el vacío y el fallo se distinguen.
 */
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { Schemas } from "@/lib/api-types";

const { apiGet, filtros } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  filtros: { valor: {} as Record<string, string> },
}));
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiGet,
}));
vi.mock("@/lib/filters", () => ({ useFilterParams: () => filtros.valor }));

import { CompetidoresBajas } from "../_components/competidores-bajas";
import { CompetidoresSegmentos } from "../_components/competidores-segmentos";

const SCOPE: Schemas["MetricScope"] = {
  label: "Cuota dentro del segmento tecnológico observado",
  universe: "technology_observed",
  denominator_records: 3,
  denominator_amount_eur: 636_000,
  filters: { cpv_prefix: "72" },
  sources: ["placsp"],
  filter_versions: [],
  model_versions: [],
  window_from: null,
  window_to: "2026-10-23",
  computed_at: "2026-10-23T10:00:00Z",
  caveat: "No representa todo el mercado español.",
};

const HHI: Schemas["HhiResult"] = {
  items: [
    { segmento: "72", empresas: 2, importe_total: 636_000, contratos: 3, hhi: 8347 },
    { segmento: "48", empresas: 3, importe_total: 300_000, contratos: 6, hhi: 3333 },
  ],
  segment_by: "cpv",
  scope: SCOPE,
};

const CUOTA: Schemas["CuotaResult"] = {
  items: [
    {
      empresa_id: 7,
      empresa: "Dominante SL",
      es_ute: 0,
      contratos: 2,
      importe: 600_000,
      ofertas_medias: 4,
      cuota_pct: 94.34,
    },
    { empresa_id: 8, empresa: "Menor SA", es_ute: 1, contratos: 1, importe: 36_000, ofertas_medias: null, cuota_pct: 5.66 },
  ],
  scope: SCOPE,
};

const REFERENCIA: Schemas["BajaReferencia"] = {
  contratos: 3,
  baja_media_pct: 16.67,
  baja_min_pct: 10,
  baja_max_pct: 20,
  ofertas_medias: 4,
  organo: null,
  cpv_prefix: "72",
  base: "mixta",
};

const BAJAS: Schemas["BajasResult"] = {
  items: [
    {
      grupo: "Diputación Z",
      contratos: 3,
      baja_media_pct: 20,
      baja_min_pct: 20,
      baja_max_pct: 20,
      importe_total: 300_000,
      ofertas_medias: 4,
    },
  ],
  group_by: "organo",
  base: "mixta",
};

/** Las llamadas a un endpoint, con sus parámetros de query. */
const llamadasA = (ruta: string) =>
  apiGet.mock.calls
    .filter((llamada) => llamada[0] === ruta)
    .map((llamada) => (llamada[1] as { params: { query: Record<string, unknown> } }).params.query);

function stubApi(respuestas: Partial<Record<string, unknown>> = {}) {
  const porDefecto: Record<string, unknown> = {
    "/api/v1/competitive/hhi": HHI,
    "/api/v1/competitive/cuota": CUOTA,
    "/api/v1/competitive/bajas/referencia": REFERENCIA,
    "/api/v1/competitive/bajas": BAJAS,
  };
  apiGet.mockImplementation((ruta: string) => {
    const respuesta = ruta in respuestas ? respuestas[ruta] : porDefecto[ruta];
    return respuesta instanceof Error ? Promise.reject(respuesta) : Promise.resolve(respuesta);
  });
}

function pintar(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>{ui}</TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiGet.mockReset();
  filtros.valor = {};
});

afterEach(cleanup);

describe("Concentración por segmento", () => {
  it("pinta el HHI de cada segmento con su zona, sin la barra de ámbito", async () => {
    filtros.valor = { ccaa: "Madrid", q: "sap" };
    stubApi();
    pintar(<CompetidoresSegmentos />);

    const lista = await screen.findByRole("list", { name: "Segmentos por concentración" });
    const filas = within(lista).getAllByRole("button");
    expect(filas[0]).toHaveTextContent("72 · Servicios TI y consultoría tecnológica");
    expect(filas[0]).toHaveTextContent("8.347");
    expect(filas[0]).toHaveTextContent("Mercado concentrado");
    expect(filas[1]).toHaveTextContent("3.333");
    // `/hhi` no admite filtros: no se le mandan los de la barra.
    expect(llamadasA("/api/v1/competitive/hhi")).toEqual([{ segment_by: "cpv", min_contratos: 5 }]);
    expect(screen.getByText("No representa todo el mercado español.")).toBeInTheDocument();
  });

  it("al elegir un segmento enseña quién se lo reparte y a qué baja se gana", async () => {
    stubApi();
    pintar(<CompetidoresSegmentos />);

    const fila = await screen.findByRole("button", { name: /^72 · Servicios TI/ });
    fireEvent.click(fila);
    expect(fila).toHaveAttribute("aria-pressed", "true");

    const reparto = await screen.findByRole("list", { name: "Quién se reparte el segmento" });
    expect(within(reparto).getByRole("link", { name: "Dominante SL" })).toHaveAttribute(
      "href",
      "/competencia/empresa/7",
    );
    expect(within(reparto).getByText("94,3%")).toBeInTheDocument();
    expect(within(reparto).getByText("UTE")).toBeInTheDocument();
    expect(await screen.findByText("16,7%")).toBeInTheDocument();
    expect(screen.getByText(/^Base mixta/)).toBeInTheDocument();

    expect(llamadasA("/api/v1/competitive/cuota")).toEqual([{ cpv: "72", limit: "10" }]);
    expect(llamadasA("/api/v1/competitive/bajas/referencia")).toEqual([{ cpv: "72" }]);
  });

  it("por tecnología dice que no hay desglose y no pide cuota ni referencia", async () => {
    stubApi({
      "/api/v1/competitive/hhi": {
        ...HHI,
        segment_by: "tecnologia",
        items: [{ segmento: "SAP", empresas: 4, importe_total: 1, contratos: 9, hhi: 1200 }],
      },
    });
    pintar(<CompetidoresSegmentos />);

    fireEvent.click(await screen.findByRole("button", { name: "Tecnología" }));
    fireEvent.click(await screen.findByRole("button", { name: /^SAP/ }));

    expect(await screen.findByText(/Por tecnología no hay desglose de cuota ni de baja de referencia/)).toBeInTheDocument();
    expect(llamadasA("/api/v1/competitive/cuota")).toEqual([]);
    expect(llamadasA("/api/v1/competitive/bajas/referencia")).toEqual([]);
  });

  it("un segmento sin bajas comparables lo dice en vez de enseñar un 0 %", async () => {
    stubApi({
      "/api/v1/competitive/bajas/referencia": { ...REFERENCIA, contratos: 0, baja_media_pct: null },
    });
    pintar(<CompetidoresSegmentos />);

    fireEvent.click(await screen.findByRole("button", { name: /^48 · Software/ }));
    expect(await screen.findByText(/Sin adjudicaciones con presupuesto y baja comparables/)).toBeInTheDocument();
  });

  it("sin segmentos con masa suficiente, lo dice; si falla, ofrece reintentar", async () => {
    stubApi({ "/api/v1/competitive/hhi": { ...HHI, items: [] } });
    pintar(<CompetidoresSegmentos />);
    expect(await screen.findByText("Ningún segmento con masa suficiente")).toBeInTheDocument();
    cleanup();

    stubApi({ "/api/v1/competitive/hhi": new Error("caída") });
    pintar(<CompetidoresSegmentos />);
    expect(await screen.findByText("No se pudo cargar la concentración por segmento")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Reintentar/ })).toBeInTheDocument();
  });
});

describe("Bajas medias", () => {
  it("pide con la parte de la barra que /bajas entiende y nombra la que no", async () => {
    filtros.valor = { ccaa: "Madrid", fecha_desde: "2026-01-01", q: "sap", estado: "ABIERTO" };
    stubApi();
    pintar(<CompetidoresBajas />);

    const tabla = await screen.findByRole("table", { name: /Bajas medias por órgano/ });
    const fila = within(tabla).getByRole("row", { name: /Diputación Z/ });
    expect(fila).toHaveTextContent("20,0%");
    expect(screen.getByText(/no aplica texto, estado\./)).toBeInTheDocument();
    expect(screen.getByText(/^Base mixta/)).toBeInTheDocument();
    expect(llamadasA("/api/v1/competitive/bajas")).toEqual([
      { ccaa: "Madrid", fecha_desde: "2026-01-01", group_by: "organo", min_contratos: "3", limit: "15" },
    ]);
  });

  it("cambiar el corte vuelve a pedir agrupando por él", async () => {
    stubApi();
    pintar(<CompetidoresBajas />);
    await screen.findByRole("table");

    fireEvent.click(screen.getByRole("button", { name: "Familia CPV" }));
    await screen.findByRole("table", { name: /Bajas medias por familia cpv/ });
    expect(llamadasA("/api/v1/competitive/bajas").map((q) => q.group_by)).toEqual(["organo", "cpv"]);
  });

  it("sin grupos comparables en el ámbito, lo dice", async () => {
    stubApi({ "/api/v1/competitive/bajas": { ...BAJAS, items: [] } });
    pintar(<CompetidoresBajas />);
    expect(await screen.findByText("Ningún grupo con bajas comparables en el ámbito")).toBeInTheDocument();
  });
});
