/**
 * La vista Competidores entera, contra el contrato de la API.
 *
 * Tres cosas se fijan aquí y solo se ven con la pantalla montada:
 *
 * - **Los nombres del contrato.** Las fixtures están tipadas con los esquemas
 *   generados del OpenAPI (`CompetitorResult`, `MovimientosVigiladasResult`).
 *   Hasta 2026-10 la pantalla declaraba sus tipos a mano y leía dos campos que
 *   la respuesta nunca trajo; con estas fixtures, un campo que el backend
 *   renombre deja de compilar aquí.
 * - **El ámbito recortado se dice.** `truncado` viajaba y nadie lo enseñaba.
 * - **Las dos acciones de una fila** —abrir su perfil y meterla en el cara a
 *   cara— llegan a donde tienen que llegar: la petición del perfil con las
 *   identidades del grupo, y el panel con las dos empresas.
 */
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { Schemas } from "@/lib/api-types";

const { fetchWithAuth, apiGet } = vi.hoisted(() => ({ fetchWithAuth: vi.fn(), apiGet: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ fetchWithAuth, apiGet }));

vi.mock("@/lib/filters", () => ({
  useFilterParams: () => ({}),
  useFilters: () => ({ ccaas: [], setCcaas: vi.fn() }),
}));

// «Contra ti» es contra la organización activa; aquí basta con que haya una.
vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => 1,
  organizacionResuelta: () => true,
}));

// El control «Vigilar» y la exportación no son el sujeto: piden su propio
// estado de sesión. Se prueban en sus ficheros.
vi.mock("@/components/seguir-boton", () => ({ SeguirBoton: () => null }));
vi.mock("@/components/export-popover", () => ({ ExportPopover: () => null }));

// El mapa es recharts: en jsdom solo añade ruido y tiempo. Las empresas se
// abren desde el ranking, que tiene un botón real por fila.
vi.mock("@/components/charts/competitors-charts", () => ({
  ALTO_MAPA_COMPETIDORES: 380,
  CompetidoresMapaChart: () => null,
}));

import CompetidoresView from "../_components/competidores-view";

type CompetitorResult = Schemas["CompetitorResult"];
type CompetitorEntry = Schemas["CompetitorEntry"];

const empresa = (over: Partial<CompetitorEntry> & { nombre: string }): CompetitorEntry => ({
  count: 0,
  importe: 0,
  cuota: 0,
  contratos_por_anio: 0,
  importe_medio: 0,
  n_organos: 0,
  pct_top_organo: 0,
  es_agrupacion: false,
  ...over,
});

const COMPETIDORES: CompetitorResult = {
  competitors: [
    empresa({
      nombre: "Acme Sistemas",
      empresa_id: 7,
      empresa_ids: [7, 8],
      es_agrupacion: true,
      count: 10,
      importe: 1_000_000,
      cuota: 40,
      importe_medio: 100_000,
      baja_media: 20,
      ofertas_medias: 3.5,
      pct_monopolio: 10,
      n_organos: 6,
      pct_top_organo: 30,
    }),
    empresa({
      nombre: "Beta Consulting",
      empresa_id: 9,
      count: 4,
      importe: 400_000,
      cuota: 16,
      importe_medio: 100_000,
      baja_media: 5,
      n_organos: 2,
      pct_top_organo: 75,
    }),
  ],
  hhi: 1856,
  pct_oferta_unica: 27,
  pct_pyme: 18,
  total_adjudicaciones: 25,
  total_empresas: 2,
  importe_total: 2_500_000,
  heatmap_ccaa: [{ empresa: "Acme Sistemas", ccaa: "Madrid", count: 6 }],
  estacionalidad: [{ mes: 12, count: 9, importe: 900_000 }],
  scatter_data: [],
  truncado: false,
  limite_filas: 5000,
};

const MOVIMIENTOS: Schemas["MovimientosVigiladasResult"] = {
  desde: "2026-09-09",
  dias: 30,
  empresas: [{ empresa_id: 9, nombre: "Beta Consulting", adjudicaciones: 1, importe: 90_000 }],
  senales: [],
  senales_truncadas: false,
};

const CONTRA_MI: Schemas["BatallasContraMi"] = {
  empresa_key: "7",
  n: 0,
  ventana: "últimos 24 meses",
  sin_nif_propio: false,
  contradicciones: 0,
  claves: ["7"],
  batallas: [],
};

const STATS = { pct_importe: 99, importe_total: 1, importe_enlazado: 1 };

/** URLs pedidas con `fetchWithAuth`, en orden. */
const urls = () => fetchWithAuth.mock.calls.map((llamada) => String(llamada[0]));

/**
 * El ranking, que es donde están los botones por empresa que aquí se pulsan.
 * El reparto de arriba tiene otro botón con el mismo nombre para cada una.
 */
const ranking = () => screen.findByRole("table", { name: /^Ranking de competidores/ });

function renderVista(competidores: CompetitorResult = COMPETIDORES) {
  fetchWithAuth.mockImplementation((url: string) => {
    if (url.includes("/analytics/competitors")) return Promise.resolve(competidores);
    if (url.includes("/contra-mi")) return Promise.resolve(CONTRA_MI);
    if (url.includes("/empresas/stats")) return Promise.resolve(STATS);
    // El perfil se deja pendiente: lo que se comprueba es que se pide bien.
    return new Promise(() => {});
  });
  apiGet.mockResolvedValue(MOVIMIENTOS);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <CompetidoresView />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fetchWithAuth.mockReset();
  apiGet.mockReset();
});

afterEach(cleanup);

describe("Competidores — la vista contra el contrato", () => {
  it("el titular suma las cuotas de la API sobre el total del ámbito", async () => {
    renderVista();

    const titular = await screen.findByRole("heading", { level: 2, name: /se reparten/ });
    // 40 + 16: las cuotas que manda la API, no un recálculo sobre los importes.
    expect(titular).toHaveTextContent("2 empresas se reparten el 56% de los");
    expect(titular).toHaveTextContent("adjudicados en el ámbito");
  });

  it("por adjudicaciones, el titular cuenta contra el total del ámbito", async () => {
    renderVista();

    fireEvent.click(await screen.findByRole("button", { name: "Adjudicaciones" }));
    // 10 + 4 de las 25 del ámbito: no de las 14 que suman las dos recibidas.
    expect(await screen.findByRole("heading", { level: 2, name: /se llevan/ })).toHaveTextContent(
      "2 empresas se llevan el 56% de las 25 adjudicaciones del ámbito",
    );
  });

  it("pinta las pymes, que la API mandaba y la pantalla no enseñaba", async () => {
    renderVista();

    expect(await screen.findByText("18,0%")).toBeInTheDocument();
    expect(screen.getByText("Adjudicaciones a pymes")).toBeInTheDocument();
  });

  it("sin cobertura del dato de ofertantes, «Oferta única» se abstiene", async () => {
    renderVista();

    // `cobertura_ofertas_pct` puede no venir: un 27 % sin denominador no se publica.
    expect(await screen.findByText("sin cobertura medida del dato de origen")).toBeInTheDocument();
    expect(screen.queryByText("27,0%")).not.toBeInTheDocument();
  });

  it("con cobertura suficiente, «Oferta única» se publica", async () => {
    renderVista({ ...COMPETIDORES, cobertura_ofertas_pct: 64 } as CompetitorResult);

    expect(await screen.findByText("27,0%")).toBeInTheDocument();
  });

  it("no avisa de recorte cuando la API analizó el ámbito entero", async () => {
    renderVista();

    await screen.findByRole("heading", { level: 2, name: /se reparten/ });
    expect(screen.queryByText("Ámbito recortado")).not.toBeInTheDocument();
  });

  it("dice que el ámbito está recortado cuando la API lo marca", async () => {
    renderVista({ ...COMPETIDORES, truncado: true, limite_filas: 5000 });

    expect(await screen.findByText("Ámbito recortado")).toBeInTheDocument();
    expect(screen.getByText(/salen de las 5\.000 más recientes/)).toBeInTheDocument();
  });

  it("el perfil arranca abierto con la primera y pide todas sus identidades", async () => {
    renderVista();

    expect(await screen.findByRole("region", { name: "Perfil de Acme Sistemas" })).toBeInTheDocument();
    await waitFor(() => expect(urls().some((u) => u.includes("/competitive/empresas/7/perfil"))).toBe(true));
    const perfil = new URL(urls().find((u) => u.includes("/perfil"))!, "http://localhost");
    // Una agrupación se pide con el grupo entero: el perfil las suma.
    expect(perfil.searchParams.get("empresa_ids")).toBe("7,8");
  });

  it("pulsar otra empresa en el ranking abre su perfil", async () => {
    renderVista();

    fireEvent.click(within(await ranking()).getByRole("button", { name: "Beta Consulting" }));

    expect(await screen.findByRole("region", { name: "Perfil de Beta Consulting" })).toBeInTheDocument();
    await waitFor(() => expect(urls().some((u) => u.includes("/competitive/empresas/9/perfil"))).toBe(true));
  });

  it("«Comparar» abre el cara a cara contra el perfil abierto, y «Quitar» lo cierra", async () => {
    renderVista();

    fireEvent.click(await screen.findByRole("button", { name: "Comparar Beta Consulting con el perfil abierto" }));

    const duelo = await screen.findByRole("table", { name: "Comparación de Acme Sistemas y Beta Consulting" });
    // Acme gana 10 y Beta 4: las dos cifras, cada una en su lado.
    const adjudicaciones = within(duelo).getByText("Adjudicaciones").closest("tr")!;
    expect(adjudicaciones).toHaveTextContent("10");
    expect(adjudicaciones).toHaveTextContent("4");
    // Beta no trae ofertas medias: se dice, no se pinta un cero.
    expect(within(duelo).getByText("Ofertas por expediente").closest("tr")).toHaveTextContent("sin dato");

    fireEvent.click(screen.getByRole("button", { name: "Quitar" }));
    expect(screen.queryByRole("table", { name: /^Comparación de/ })).not.toBeInTheDocument();
  });

  it("la empresa del perfil abierto no se compara consigo misma", async () => {
    renderVista();

    expect(await screen.findByRole("button", { name: "Comparar Acme Sistemas con el perfil abierto" })).toBeDisabled();
  });

  it("marca en el ranking las empresas que vigilas", async () => {
    renderVista();

    const tabla = await ranking();
    const fila = within(tabla).getByRole("button", { name: "Beta Consulting" }).closest("tr")!;
    expect(await within(fila).findByText("La vigilas")).toBeInTheDocument();
    const otra = within(tabla).getByRole("button", { name: "Acme Sistemas" }).closest("tr")!;
    expect(within(otra).queryByText("La vigilas")).not.toBeInTheDocument();
  });

  it("«Tabla completa» devuelve las doce columnas, con las mismas dos acciones", async () => {
    renderVista();

    fireEvent.click(await screen.findByRole("button", { name: "Tabla completa" }));

    expect(await screen.findByRole("columnheader", { name: /NIF/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Contratos\/año/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Comparar Beta Consulting con el perfil abierto" })).toBeInTheDocument();
  });

  it("la búsqueda filtra el ranking pero no el titular", async () => {
    renderVista();

    const tabla = await ranking();
    fireEvent.change(screen.getByRole("combobox", { name: "Buscar empresa o NIF" }), {
      target: { value: "beta" },
    });

    await waitFor(() =>
      expect(within(tabla).queryByRole("button", { name: "Acme Sistemas" })).not.toBeInTheDocument(),
    );
    expect(within(tabla).getByRole("button", { name: "Beta Consulting" })).toBeInTheDocument();
    // El titular y el reparto hablan del mercado: Acme sigue en los dos.
    expect(screen.getByRole("heading", { level: 2, name: /se reparten/ })).toHaveTextContent("el 56%");
    expect(screen.getByRole("button", { name: "Acme Sistemas" })).toBeInTheDocument();
  });
});
