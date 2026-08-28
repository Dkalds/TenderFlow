import * as React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * Lo que fija este suite: el ámbito activo llega a las DOS peticiones de la
 * vista, no sólo al ranking.
 *
 * El drill-down se pedía con un `fetch` desnudo, sin un solo parámetro. Entrando
 * en `/mercado?tecnologia=SAP&vista=organos` y abriendo un órgano, la tabla
 * contaba sus licitaciones SAP y el panel de al lado respondía con el histórico
 * completo del órgano — mismo encabezado, dos universos.
 */

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

// `useFilteredQuery` lee el ámbito de aquí; ExportPopover también.
const mockFilterParams = vi.fn<() => Record<string, string>>();
vi.mock("@/lib/filters", () => ({
  useFilterParams: () => mockFilterParams(),
}));

// Los gráficos no son el sujeto: recharts en jsdom sólo añade ruido y tiempo.
vi.mock("@/components/charts/organos-charts", () => ({
  OrganosRankingChart: () => null,
  OrganosTreemapChart: () => null,
  OrganosAdjudicatariosChart: () => null,
  OrganosEstacionalidadChart: () => null,
}));

import OrganosView from "../organos-view";

const LISTA = {
  organos: [
    {
      organo_contratacion: "ORG A",
      count: 2,
      importe: 1_500_000,
      pct: 66.67,
      ccaa: "Madrid",
    },
  ],
  total_organos: 1,
  importe_total: 1_500_000,
  concentracion_top10: 100,
  treemap_breakdown: [],
};

const DETALLE = {
  kpis: {
    total_licitaciones: 1,
    importe_total: 1_000_000,
    importe_medio: 1_000_000,
    pct_adjudicado: 100,
    lead_time_medio: 10,
    top_adjudicatario: "CONSULTORA SAP",
    top_adj_importe: 900_000,
  },
  top_adjudicatarios: [{ nombre: "CONSULTORA SAP", count: 1, importe: 900_000 }],
  estacionalidad: [{ mes_numero: 1, count: 1 }],
  top_scored: [],
};

function makeResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

/** El detalle lleva el nombre del órgano en el path; el ranking no. */
const ES_DETALLE = /\/analytics\/organos\/[^?/]/;

/**
 * Presupuesto de espera de las aserciones asíncronas de este fichero.
 *
 * El default de testing-library es 1 s de **reloj de pared**, y aquí eso es un
 * umbral de latencia disfrazado de aserción: lo que se afirma es que la petición
 * acaba saliendo con el ámbito activo, no que salga en menos de un segundo. En
 * una máquina con la CPU saturada (varios runners a la vez, antivirus mordiendo
 * el disco) el render de esta vista —cuatro gráficos mockeados, una tabla y dos
 * queries— se acerca a ese segundo: el caso del drill-down se midió en 710 ms.
 *
 * Subirlo no debilita nada: si la reactividad se rompiera, la condición no se
 * cumpliría tampoco a los 15 s, sólo tardaría más en decirlo.
 */
const ESPERA_MS = 15_000;

/**
 * Tope del caso completo. Tiene que ir por encima de `ESPERA_MS` o el default de
 * vitest (5 s) abortaría el caso antes de que la espera llegue a agotarse, y el
 * fallo diría «timeout» en vez de decir qué URL faltaba.
 */
const TIMEOUT_CASO = 30_000;

/** URLs pedidas hasta ahora, en orden. */
function urls(): string[] {
  return (global.fetch as ReturnType<typeof vi.fn>).mock.calls.map(
    (call) => String(call[0]),
  );
}

function urlDetalle(): string | undefined {
  return urls().find((u) => ES_DETALLE.test(u));
}

function renderPage() {
  // Un solo QueryClient por render: el re-render del cambio de ámbito tiene que
  // refetchear por la key, no porque le hayamos vaciado la caché debajo. El
  // elemento se construye de nuevo en cada pasada — React descarta el re-render
  // si le llega la misma referencia y el cambio de ámbito no llegaría a correr.
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const ui = () =>
    React.createElement(
      QueryClientProvider,
      { client: queryClient },
      React.createElement(OrganosView),
    );
  const utils = render(ui());
  return { ...utils, rerenderPage: () => utils.rerender(ui()) };
}

beforeEach(() => {
  mockFilterParams.mockReturnValue({});
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockImplementation((input: RequestInfo | URL) =>
      Promise.resolve(makeResponse(ES_DETALLE.test(String(input)) ? DETALLE : LISTA)),
    ),
  );
});

afterEach(() => {
  // Desmontar **antes** de retirar el doble de `fetch`, y no dejarlo en manos
  // del cleanup automático de testing-library. Ese cleanup está registrado al
  // importar la librería, o sea antes que este `afterEach`, y vitest ejecuta los
  // hooks en orden inverso al de registro: desmontaba después de
  // `unstubAllGlobals`, así que los árboles de los casos anteriores se
  // desmontaban con el `fetch` real —inexistente en jsdom— y sus queries en
  // vuelo quedaban colgando.
  //
  // El síntoma era desconcertante porque no era un fallo de aserción: el tercer
  // caso pasa en ~4 s ejecutado solo y tardaba 37 s cuando iba detrás de los
  // otros dos, hasta rebasar el tope de 30 s del caso. Cada árbol sin desmontar
  // seguía participando en los `act` del siguiente.
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Órganos — el ámbito llega a las dos peticiones", () => {
  it("pide el ranking con el ámbito activo", async () => {
    mockFilterParams.mockReturnValue({ tecnologia: "SAP" });

    renderPage();

    await waitFor(() => expect(urls().length).toBeGreaterThan(0), { timeout: ESPERA_MS });
    const url = new URL(urls()[0], "http://localhost");
    expect(url.pathname).toBe("/api/v1/analytics/organos");
    expect(url.searchParams.get("tecnologia")).toBe("SAP");
  }, TIMEOUT_CASO);

  it("pide el drill-down con el mismo ámbito que el ranking", async () => {
    mockFilterParams.mockReturnValue({ tecnologia: "SAP", ccaa: "Madrid" });

    renderPage();

    // La fila del listado completo lleva el nombre del órgano en su `title`.
    fireEvent.click(await screen.findByTitle("ORG A", undefined, { timeout: ESPERA_MS }));

    await waitFor(() => expect(urlDetalle()).toBeDefined(), { timeout: ESPERA_MS });

    const detalle = new URL(urlDetalle()!, "http://localhost");
    // El nombre viaja percent-encoded en el path, el ámbito en la query.
    expect(detalle.pathname).toBe("/api/v1/analytics/organos/ORG%20A");
    expect(detalle.searchParams.get("tecnologia")).toBe("SAP");
    expect(detalle.searchParams.get("ccaa")).toBe("Madrid");
  }, TIMEOUT_CASO);

  it("vuelve a pedir el drill-down cuando cambia el ámbito", async () => {
    mockFilterParams.mockReturnValue({ tecnologia: "SAP" });

    const { rerenderPage } = renderPage();

    fireEvent.click(await screen.findByTitle("ORG A", undefined, { timeout: ESPERA_MS }));
    await waitFor(() => expect(urlDetalle()).toBeDefined(), { timeout: ESPERA_MS });

    // Cambiar de tecnología no puede dejar el panel anterior en pantalla: los
    // filtros forman parte de la key, así que la query se vuelve a pedir.
    mockFilterParams.mockReturnValue({ tecnologia: "SALESFORCE" });

    // El `act` asíncrono no es adorno. `rerender()` a secas sólo agota el
    // trabajo **síncrono** de React: deja encolado el efecto con el que React
    // Query monta el observador de la key nueva y lanza su fetch. Ese hueco se
    // le da luego al `waitFor`… que en este montaje no llega a cerrarlo: envuelve
    // su sondeo en su propio `act` y se queda esperando indefinidamente —el caso
    // moría por timeout del test (30 s) sin llegar a evaluar su propia espera de
    // 15 s, con duraciones medidas de 80 s y 167 s—. Con `await act` las
    // microtareas del efecto corren aquí, y para cuando se mira `urls()` la
    // petición del ámbito nuevo ya salió (medido: el caso pasa en ~0,5 s).
    //
    // No se relaja la aserción: la petición sigue teniendo que existir, con su
    // path y su query. Lo que cambia es que se la espera donde se produce.
    await act(async () => {
      rerenderPage();
    });

    await waitFor(
      () =>
        expect(
          urls().some((u) => ES_DETALLE.test(u) && u.includes("tecnologia=SALESFORCE")),
        ).toBe(true),
      { timeout: ESPERA_MS },
    );
  }, TIMEOUT_CASO);
});
