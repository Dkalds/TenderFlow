import * as React from "react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { parseAsString, useQueryState } from "nuqs";
import { withNuqsTestingAdapter } from "nuqs/adapters/testing";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * Paridad del prefetch de Detalle con los hooks de la pantalla: misma clave y
 * misma ruta para la primera página del listado y, con `?lic=`, para la ficha.
 * Si divergen, el servidor paga la petición y el navegador la repite.
 *
 * Se montan los mismos hooks que `DetalleView` y en el mismo orden: los filtros
 * del listado (ámbito, ventana de cierre y etiqueta), el estado inicial de la
 * tabla y las consultas. El segundo test fija que la vista sigue componiéndolos
 * así.
 */

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));
vi.mock("@/hooks/use-organization", () => ({ useActiveOrganizationId: () => 7 }));

import { useFilters } from "@/lib/filters";
import { useDetalleQueries } from "../../_hooks/use-detalle-queries";
import { useDetalleTableState } from "../../_hooks/use-detalle-table";
import { useFiltrosDelListado } from "../../_hooks/use-filtros-listado";
import { PARAMETRO_FICHA, consultasDetalle } from "../prefetch";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function useListadoDeLaPantalla() {
  const { queryFilters } = useFiltrosDelListado();
  const { q } = useFilters();
  const tabla = useDetalleTableState({ filterParams: queryFilters, q });
  const [detailId] = useQueryState(PARAMETRO_FICHA, parseAsString);
  return useDetalleQueries({ queryParams: tabla.queryParams, detailId });
}

const URLS = [
  "",
  "?tecnologia=SAP&ccaa=MD&cierre_hasta=2026-08-27",
  // Una ventana ilegible no entra en la query, ni en el hook ni en servidor.
  "?q=erp&solo_abiertas=true&cierre_desde=27/08/2026&importe_min=1000",
  "?estado=PUB,EV&lic=2026%2F0410&ficha=completa",
];

describe("prefetch de Detalle", () => {
  it.each(URLS)("la clave y la ruta coinciden con las de los hooks para %j", async (search) => {
    // Sin filas, para que no salga también el scoring de la página.
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(jsonResponse({ items: [], total: 0, next_cursor: null })));
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const Nuqs = withNuqsTestingAdapter({ searchParams: search });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Nuqs>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </Nuqs>
    );

    const consultas = consultasDetalle(Object.fromEntries(new URLSearchParams(search)));
    renderHook(() => useListadoDeLaPantalla(), { wrapper });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(consultas.length));

    const pedidas = fetchMock.mock.calls.map((call) => callUrl(call));
    for (const consulta of consultas) {
      expect(client.getQueryState(consulta.queryKey)).toBeDefined();
      expect(pedidas).toContain(consulta.path);
    }
    expect(consultas).toHaveLength(search.includes(`${PARAMETRO_FICHA}=`) ? 2 : 1);
  });

  it("la vista compone los hooks igual que este test", () => {
    const vista = readFileSync(join(__dirname, "..", "..", "_components", "detalle-view.tsx"), "utf8").replace(
      /\s+/g,
      " ",
    );
    expect(vista).toContain("const { cierre, etiqueta, queryFilters } = useFiltrosDelListado();");
    expect(vista).toContain("useDetalleTableState({ filterParams: queryFilters, q })");
    expect(vista).toContain("useQueryState( PARAMETRO_FICHA,");
    expect(vista).toContain("queryParams: tabla.queryParams, detailId,");
  });
});
