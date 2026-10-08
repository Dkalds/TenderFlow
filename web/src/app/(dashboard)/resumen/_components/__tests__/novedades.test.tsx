/**
 * Una sola idea de «nuevo» en el mercado: desde tu última visita, en tu ámbito.
 *
 * Fija las tres piezas que la sostienen fuera de la tarjeta (que tiene sus
 * propios tests en `atencion-cards.test.tsx`): la consulta lleva el ámbito,
 * «Marcar todo como visto» la vuelve a pedir, y la tabla de publicaciones dice
 * qué significa el punto de las filas nuevas — solo cuando hay alguna.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";

const h = vi.hoisted(() => ({
  params: {} as Record<string, string>,
  timeline: [] as Record<string, unknown>[],
  novedades: { count: 0, sample: [], desde: "2026-09-29T08:15:00+00:00" } as Record<
    string,
    unknown
  >,
}));

const fetchWithAuth = vi.hoisted(() =>
  vi.fn((url: string) => {
    if (url.includes("/resumen/novedades")) return Promise.resolve(h.novedades);
    if (url.includes("/resumen/timeline")) {
      return Promise.resolve({ items: h.timeline, total: h.timeline.length, muestreado: false });
    }
    return new Promise(() => {});
  }),
);
const apiMutate = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api-client", () => ({ fetchWithAuth, apiMutate, apiGet: vi.fn() }));
vi.mock("@/lib/filters", async () => {
  const real = await vi.importActual<typeof import("@/lib/filters")>("@/lib/filters");
  return {
    ...real,
    useFilterParams: () => h.params,
    useFilters: () => ({ rango: { desde: null, hasta: null } }),
  };
});

import { useNovedades } from "../../_hooks/use-novedades";
import { useMarcarVisto } from "../desde-ultima-visita";
import { UltimasPublicaciones } from "../ultimas-publicaciones";
import { analyticsKeys } from "@/lib/query-keys";

function cliente() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
}

function envoltorio(qc: QueryClient) {
  return function Envoltorio({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={qc}>
        <TooltipProvider>{children}</TooltipProvider>
      </QueryClientProvider>
    );
  };
}

function fila(id: string, fechaPublicacion: string, fuente = "placsp") {
  return {
    id_externo: id,
    titulo: `Expediente ${id}`,
    importe: 1000,
    fecha_publicacion: fechaPublicacion,
    estado: "PUB",
    organo_contratacion: "Ministerio",
    tipo_contrato: "2",
    ccaa: "Madrid",
    fuente,
  };
}

afterEach(() => {
  cleanup();
  fetchWithAuth.mockClear();
  apiMutate.mockReset();
  h.params = {};
  h.timeline = [];
});

describe("useNovedades", () => {
  it("pide las novedades con el ámbito de la barra", async () => {
    h.params = { ccaa: "Madrid", estado: "PUB" };
    const { result } = renderHook(() => useNovedades(), { wrapper: envoltorio(cliente()) });

    await waitFor(() => expect(result.current.data).toBeDefined());
    const url = fetchWithAuth.mock.calls.map(([u]) => u).find((u) => u.includes("novedades"));
    expect(url).toContain("ccaa=Madrid");
    expect(url).toContain("estado=PUB");
  });
});

describe("useMarcarVisto", () => {
  it("vuelve a pedir las novedades del ámbito, que cuelgan de la misma marca", async () => {
    apiMutate.mockResolvedValue({ visto_en: "2026-10-01T10:00:00+00:00" });
    h.params = { ccaa: "Madrid" };
    const qc = cliente();
    const novedades = renderHook(() => useNovedades(), { wrapper: envoltorio(qc) });
    await waitFor(() => expect(novedades.result.current.data).toBeDefined());
    const pedidasAntes = fetchWithAuth.mock.calls.length;

    const marcar = renderHook(() => useMarcarVisto(), { wrapper: envoltorio(qc) });
    await act(async () => {
      await marcar.result.current.mutateAsync();
    });

    // La clave completa lleva URL y filtros detrás del prefijo: la invalidación
    // tiene que alcanzarla igualmente.
    const estados = qc.getQueryCache().findAll({ queryKey: analyticsKeys.novedades });
    expect(estados.length).toBe(1);
    await waitFor(() => expect(fetchWithAuth.mock.calls.length).toBeGreaterThan(pedidasAntes));
  });
});

describe("UltimasPublicaciones · filas nuevas", () => {
  it("explica el punto cuando hay alguna fila nueva", async () => {
    h.timeline = [fila("NUEVA", "2026-09-30T09:00:00+00:00"), fila("VIEJA", "2026-09-20T09:00:00+00:00")];
    render(<UltimasPublicaciones />, { wrapper: envoltorio(cliente()) });

    expect(await screen.findByText("nuevas desde tu última visita")).toBeInTheDocument();
    // La tabla (escritorio) y las fichas (teléfono) se pintan las dos; el CSS
    // decide cuál se ve. En cada una, una sola fila es nueva.
    const tabla = screen.getByRole("table");
    expect(within(tabla).getAllByText("Nueva desde tu última visita.")).toHaveLength(1);
  });

  it("sin filas nuevas no hay leyenda que explicar", async () => {
    h.timeline = [fila("VIEJA", "2026-09-20T09:00:00+00:00")];
    render(<UltimasPublicaciones />, { wrapper: envoltorio(cliente()) });

    expect(await within(screen.getByRole("table")).findByText("Expediente VIEJA")).toBeInTheDocument();
    expect(screen.queryByText("nuevas desde tu última visita")).not.toBeInTheDocument();
  });

  it("«Nuevas» deja solo las filas publicadas después de tu última visita", async () => {
    h.timeline = [fila("NUEVA", "2026-09-30T09:00:00+00:00"), fila("VIEJA", "2026-09-20T09:00:00+00:00")];
    render(<UltimasPublicaciones />, { wrapper: envoltorio(cliente()) });

    expect(await within(screen.getByRole("table")).findByText("Expediente VIEJA")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /^Nuevas/ }));

    const tabla = screen.getByRole("table");
    expect(within(tabla).getByText("Expediente NUEVA")).toBeInTheDocument();
    expect(within(tabla).queryByText("Expediente VIEJA")).not.toBeInTheDocument();
  });
});

describe("UltimasPublicaciones · origen", () => {
  it("dice de qué portal viene cada expediente", async () => {
    h.timeline = [fila("T1", "2026-09-20T09:00:00+00:00", "ted"), fila("P1", "2026-09-19T09:00:00+00:00")];
    render(<UltimasPublicaciones />, { wrapper: envoltorio(cliente()) });

    const tabla = screen.getByRole("table");
    expect(within(tabla).getByRole("columnheader", { name: /Origen/ })).toBeInTheDocument();
    expect(await within(tabla).findByText("TED")).toBeInTheDocument();
    expect(within(tabla).getByText("PLACSP")).toBeInTheDocument();
  });
});
