/**
 * Catálogos de `/meta/filters`.
 *
 * El hook nació de un bug de duplicación: el mismo endpoint se pedía con
 * `["meta-filters"]` desde `layout/scope-bar.tsx` y con `["meta-ccaas"]` desde
 * `mi-watchlist/page.tsx`, esta última quedándose sólo con las CCAA. Dos
 * entradas de caché y dos peticiones para una respuesta idéntica, en pantallas
 * que se montan juntas.
 *
 * La corrección es una sola clave de registro (`metaKeys.filters`): quien
 * necesite una dimensión la proyecta con `select` sobre esa misma clave, sin
 * una segunda petición.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { useMetaFilters, type MetaFilters } from "@/hooks/use-meta-filters";
import { metaKeys } from "@/lib/query-keys";
import { callUrl, jsonResponse } from "./fetch-call";

const CATALOGOS: MetaFilters = {
  estado: ["PUB", "ADJ"],
  ccaa: ["MD", "CT"],
  tecnologia: ["SAP", "MICROSOFT"],
  cpv: ["72000000"],
};

/**
 * Un `QueryClient` por test, devuelto junto al wrapper.
 *
 * Se crea fuera del componente a propósito: un `new QueryClient()` dentro del
 * cuerpo del wrapper se rehace en cada render y cada uno traería su propia
 * caché vacía, con lo que «¿cuántas peticiones se hicieron?» —la pregunta de
 * este fichero— dejaría de tener sentido.
 */
function crearEntorno() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, wrapper: Wrapper };
}

function stub(body: unknown) {
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(body)));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useMetaFilters", () => {
  it("pide los catálogos a /meta/filters y los devuelve enteros", async () => {
    const fetchMock = stub(CATALOGOS);
    const { wrapper } = crearEntorno();

    const { result } = renderHook(() => useMetaFilters(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(CATALOGOS);
    expect(fetchMock.mock.calls.map(callUrl)).toEqual(["/api/v1/meta/filters"]);
  });

  it("no pide nada cuando llega deshabilitado", () => {
    // La barra de ámbito lo monta en rutas donde el catálogo no se usa: pedirlo
    // igual sería una petición por navegación a cambio de nada.
    const fetchMock = stub(CATALOGOS);
    const { wrapper } = crearEntorno();

    const { result } = renderHook(() => useMetaFilters(false), { wrapper });

    expect(result.current.fetchStatus).toBe("idle");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("guarda la respuesta bajo la clave del registro, no bajo una literal suya", async () => {
    // Si el hook volviera a inventarse `["meta-filters"]`, la clave dejaría de
    // ser la que comparten las proyecciones y volveríamos al bug original.
    const { client, wrapper } = crearEntorno();
    stub(CATALOGOS);

    const { result } = renderHook(() => useMetaFilters(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryData(metaKeys.filters)).toEqual(CATALOGOS);
  });
});
