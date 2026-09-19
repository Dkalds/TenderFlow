import * as React from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * Montaje común de los tests de `components/pliego/`: un `QueryClient` sin
 * reintentos por test y un `fetch` que responde por ruta.
 *
 * Una respuesta nueva por llamada: un `Response` sólo se lee una vez (ver
 * `use-follows.test.tsx`).
 */
export function renderConQuery(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

type Ruta = [RegExp, unknown, number?];

/** `fetch` doble que responde según la primera ruta que case con la URL. */
export function fetchPorRuta(...rutas: Ruta[]) {
  const fn = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : String(input);
    const ruta = rutas.find(([patron]) => patron.test(url));
    if (!ruta) return Promise.resolve(jsonResponse({ detail: `sin doble para ${url}` }, 404));
    return Promise.resolve(jsonResponse(ruta[1], ruta[2] ?? 200));
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}
