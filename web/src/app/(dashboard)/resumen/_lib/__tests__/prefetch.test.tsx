import * as React from "react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { withNuqsTestingAdapter } from "nuqs/adapters/testing";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * El prefetch del Resumen sólo sirve si su clave es **exactamente** la que
 * pedirán las bandas en el navegador. Este suite lo comprueba de las dos formas
 * que pueden romperse:
 *
 * 1. Paridad de clave y URL: el hook real (`useFilteredQuery`, con nuqs leyendo
 *    la misma URL) cachea bajo la clave que calcula `consultasResumen` y pide
 *    la misma ruta.
 * 2. Que las bandas sigan pidiendo esas consultas: si alguien cambia la
 *    `baseKey` o la ruta en un componente, el prefetch dejaría de servir en
 *    silencio.
 */

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));

import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { filterParamsFromSearch } from "@/lib/filter-params";
import { CONSULTAS_CON_AMBITO_RESUMEN, consultasResumen } from "../prefetch";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const URLS = ["", "?tecnologia=SAP&ccaa=MD", "?q=erp&solo_abiertas=true&importe_min=0"];

describe("prefetch del Resumen", () => {
  it.each(URLS)("la clave y la ruta coinciden con las del hook para %j", async (search) => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({})));
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const Nuqs = withNuqsTestingAdapter({ searchParams: search });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Nuqs>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </Nuqs>
    );

    renderHook(
      () => CONSULTAS_CON_AMBITO_RESUMEN.map(({ baseKey, url }) => useFilteredQuery([...baseKey], url)),
      { wrapper },
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(CONSULTAS_CON_AMBITO_RESUMEN.length));

    const consultas = consultasResumen(filterParamsFromSearch(new URLSearchParams(search)));
    const pedidas = fetchMock.mock.calls.map((call) => callUrl(call));
    for (const consulta of consultas) {
      expect(client.getQueryState(consulta.queryKey)).toBeDefined();
      expect(pedidas).toContain(consulta.path);
    }
  });

  it("las bandas del Resumen siguen pidiendo esas consultas", () => {
    const componentes = join(__dirname, "..", "..", "_components");
    const fuentes = ["contexto-strip.tsx", "atencion-cards.tsx", "composicion-panel.tsx"]
      .map((f) => readFileSync(join(componentes, f), "utf8"))
      .join("\n")
      .replace(/\s+/g, " ");
    for (const { baseKey, url } of CONSULTAS_CON_AMBITO_RESUMEN) {
      expect(fuentes).toContain(`${JSON.stringify(baseKey).replace(/,/g, ", ")}, "${url}"`);
    }
  });
});
