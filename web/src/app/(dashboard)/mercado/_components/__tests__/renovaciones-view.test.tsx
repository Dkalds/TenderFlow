import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { RenovacionRow } from "../../_hooks/use-renovaciones";

/** El `context` que `renovaciones-lista.tsx` le pasa a cada fila. */
interface RenovacionesRowContext {
  onRowActivate: (licitacionId: string) => void;
}

/**
 * Lo que fija este suite de la vista Renovaciones de Mercado:
 *
 * 1. **Los cuatro totales salen del resumen del servidor**, no de las filas.
 *    El fixture los hace incompatibles a propósito —miles de contratos y
 *    millones de euros frente a tres filas— porque el fallo que ADR-014 §2
 *    prohíbe no se ve cuando los dos números coinciden: sumar la página
 *    servida daría un número más pequeño con pinta de total.
 * 2. **Una fila que ya es tuya no ofrece «Anticipar»**. El cruce con la
 *    cartera y con las oportunidades abiertas es fila a fila y sólo decide qué
 *    se pinta en la última celda; de él no sale ningún total, y este test lo
 *    comprueba de las dos formas: la marca aparece en su fila y los KPIs no se
 *    mueven por ella.
 * 3. **Sin cruce disponible, la tabla no se bloquea**: si las dos consultas de
 *    organización no han resuelto, todas las filas vuelven a ofrecer el CTA.
 */

const navegacion = vi.hoisted(() => ({
  replace: vi.fn(),
  push: vi.fn(),
  search: new URLSearchParams(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: navegacion.replace, push: navegacion.push }),
  useSearchParams: () => navegacion.search,
}));

// El ámbito global sólo aporta la tecnología a esta vista.
vi.mock("@/lib/filters", () => ({ useFilters: () => ({ tecnologias: [] }) }));

vi.mock("@/hooks/use-organization", () => ({
  useOrganizationStore: (selector: (estado: unknown) => unknown) =>
    selector({ setActiveOrganizationId: vi.fn() }),
}));

const propias = vi.hoisted(() => ({
  cartera: [] as { licitacion_id: string }[] | undefined,
  pursuits: undefined as { items?: { licitacion_id: string }[] } | undefined,
}));
vi.mock("@/hooks/use-cartera", () => ({ useCartera: () => ({ data: propias.cartera }) }));
vi.mock("@/hooks/use-pursuits", () => ({
  usePursuits: () => ({ data: propias.pursuits }),
  useCreatePursuit: () => ({ mutateAsync: vi.fn() }),
}));

// Recharts en jsdom mide 0×0: el ranking por empresa no es el sujeto de este
// suite y sólo añadiría ruido y tiempo.
vi.mock("../renovaciones/renovaciones-cartera", () => ({
  RenovacionesCartera: () => null,
}));

/**
 * `TableVirtuoso` no pinta una sola fila en jsdom: mide el viewport y ahí todo
 * vale 0×0, así que su `tbody` sale vacío y no habría nada que afirmar sobre
 * las filas. El doble monta **el mismo contrato** —el mapa `components`, el
 * `fixedHeaderContent`, el `itemContent` y el `context` que la lista le pasa—
 * sin virtualizar, que es justo lo que no se está probando aquí.
 */
interface VirtuosoFalso {
  data: RenovacionRow[];
  context: RenovacionesRowContext;
  components: {
    Table: React.ComponentType<React.PropsWithChildren>;
    TableHead: React.ComponentType<React.PropsWithChildren>;
    TableBody: React.ComponentType<React.PropsWithChildren>;
    TableRow: React.ComponentType<
      React.PropsWithChildren<{ item: RenovacionRow; context: RenovacionesRowContext }>
    >;
  };
  fixedHeaderContent: () => React.ReactNode;
  itemContent: (index: number, item: RenovacionRow) => React.ReactNode;
}
vi.mock("react-virtuoso", () => ({
  TableVirtuoso: ({
    data,
    context,
    components,
    fixedHeaderContent,
    itemContent,
  }: VirtuosoFalso) => (
    <components.Table>
      <components.TableHead>{fixedHeaderContent()}</components.TableHead>
      <components.TableBody>
        {data.map((item, index) => (
          <components.TableRow key={item.licitacion_id} item={item} context={context}>
            {itemContent(index, item)}
          </components.TableRow>
        ))}
      </components.TableBody>
    </components.Table>
  ),
}));

const fetchWithAuth = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api-client", () => ({ fetchWithAuth }));

import RenovacionesView from "../renovaciones-view";

/** Tres contratos que vencen; ninguno de ellos suma lo que dicen los KPIs. */
const FILAS = [
  fila("EXP-PROPIO", "Mantenimiento SAP del hospital", "TU EMPRESA SL"),
  fila("EXP-ANTICIPADO", "Soporte SAP del ayuntamiento", "OTRA CONSULTORA SA"),
  fila("EXP-AJENO", "Evolutivo SAP de la diputación", "TERCERA INTEGRADORA SL"),
];

function fila(licitacionId: string, titulo: string, empresa: string) {
  return {
    licitacion_id: licitacionId,
    titulo,
    empresa,
    empresa_id: null,
    es_ute: 0,
    organo_contratacion: "ÓRGANO X",
    importe_adjudicado: 1_000_000,
    riesgo_cambio: 0.7,
    dias_restantes: 30,
    fecha_fin_efectiva: "2026-12-31",
    fecha_fin_origen: "real",
    fecha_fin_con_prorroga: null,
    prorroga_meses: null,
    retencion_model_version: 3,
    url: null,
    ccaa: "Madrid",
    cpv: null,
    duracion_unidad: null,
    duracion_valor: null,
    fecha_adjudicacion: null,
  };
}

/**
 * Totales del dataset completo: 4812 contratos, no las tres filas servidas.
 * Si alguien vuelve a derivarlos de `items`, los números de pantalla caen a 3.
 */
const TOTALES = {
  contratos_venciendo: 4812,
  importe_en_juego: 912_000_000,
  importe_alto_riesgo: 410_000_000,
  calientes: 77,
};

function pintar() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RenovacionesView />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

// La implementación se vuelve a poner en cada test y no una sola vez al cargar
// el módulo: así el `clearAllMocks` de abajo no puede dejar el `fetch` mudo si
// alguien lo cambia por un `resetAllMocks`.
beforeEach(() => {
  fetchWithAuth.mockImplementation((url: string) =>
    Promise.resolve(
      url.includes("/resumen")
        ? { months_ahead: 6, totales: TOTALES, items: [] }
        : { items: FILAS, total: FILAS.length },
    ),
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  navegacion.search = new URLSearchParams();
  propias.cartera = [];
  propias.pursuits = undefined;
});

describe("Renovaciones — los totales son del servidor", () => {
  it("pinta los totales del resumen y no el tamaño de la página servida", async () => {
    pintar();

    // 4812 contratos con 3 filas en la tabla: el KPI describe la ventana
    // entera, que es lo que el endpoint de resumen calcula.
    expect(await screen.findByText("4812")).toBeInTheDocument();
    expect(screen.getByText("77")).toBeInTheDocument();
    expect(screen.queryByText("3")).not.toBeInTheDocument();
  });

  it("mientras el resumen no llega pinta «…», nunca ceros", () => {
    pintar();
    expect(screen.getAllByText("…")).toHaveLength(4);
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });
});

describe("Renovaciones — lo que ya es tuyo", () => {
  it("una fila en cartera se marca y no ofrece «Anticipar»", async () => {
    propias.cartera = [{ licitacion_id: "EXP-PROPIO" }];
    propias.pursuits = { items: [{ licitacion_id: "EXP-ANTICIPADO" }] };
    pintar();

    await screen.findByText("En tu cartera");
    expect(screen.getByText("Anticipada")).toBeInTheDocument();

    // El CTA sobrevive sólo para el contrato ajeno, y se nombra por su fila.
    const anticipar = screen.getAllByRole("button", { name: /^Anticipar la renovación de / });
    expect(anticipar).toHaveLength(1);
    expect(anticipar[0]).toHaveAccessibleName(/Evolutivo SAP de la diputación/);

    // Y el cruce no toca los KPIs: siguen siendo los del resumen.
    expect(screen.getByText("4812")).toBeInTheDocument();
  });

  it("sin cruce disponible todas las filas vuelven a ofrecer «Anticipar»", async () => {
    // Es la degradación de una organización sin resolver: las dos consultas
    // están deshabilitadas y `data` es `undefined`.
    propias.cartera = undefined;
    propias.pursuits = undefined;
    pintar();

    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /^Anticipar la renovación de / })).toHaveLength(
        FILAS.length,
      ),
    );
    expect(screen.queryByText("En tu cartera")).not.toBeInTheDocument();
  });
});

describe("Renovaciones — el corte es enlazable", () => {
  it("siembra el horizonte desde la URL y pide esa ventana", async () => {
    navegacion.search = new URLSearchParams("meses=24");
    pintar();

    await waitFor(() =>
      expect(fetchWithAuth.mock.calls.some(([url]) => String(url).includes("months=24"))).toBe(true),
    );
    // Lo que ya está en la URL no se reescribe.
    expect(navegacion.replace).not.toHaveBeenCalled();
  });

  it("siembra la búsqueda local desde su propio parámetro, no desde `q`", async () => {
    navegacion.search = new URLSearchParams("renovacion_q=diputación");
    pintar();

    // Filtra sobre las filas ya servidas: queda la que casa y desaparecen las
    // otras dos. `q` es el ámbito global y no puede significar esto.
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /^Anticipar la renovación de / })).toHaveLength(1),
    );
    expect(screen.getByRole("searchbox")).toHaveValue("diputación");
  });
});
