/**
 * Catálogos de `/meta/filters`: una consulta, dos proyecciones.
 *
 * El hook nació de un bug de duplicación: el mismo endpoint se pedía con
 * `["meta-filters"]` desde `layout/scope-bar.tsx` y con `["meta-ccaas"]` desde
 * `mi-watchlist/page.tsx`, esta última quedándose sólo con las CCAA. Dos
 * entradas de caché y dos peticiones para una respuesta idéntica, en pantallas
 * que se montan juntas.
 *
 * La corrección es `select`: `useMetaCcaas` comparte la clave de
 * `useMetaFilters` y proyecta. Lo que hay que fijar aquí no es que devuelva las
 * CCAA —eso es trivial— sino que **no dispara una segunda petición**, que es el
 * bug que vino a arreglar y lo único que una refactorización futura podría
 * deshacer sin que nada se ponga rojo.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { useMetaCcaas, useMetaFilters, type MetaFilters } from "@/hooks/use-meta-filters";
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
    // ser la que comparte `useMetaCcaas` y volveríamos al bug original.
    const { client, wrapper } = crearEntorno();
    stub(CATALOGOS);

    const { result } = renderHook(() => useMetaFilters(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryData(metaKeys.filters)).toEqual(CATALOGOS);
  });
});

describe("useMetaCcaas", () => {
  it("proyecta sólo las CCAA", async () => {
    stub(CATALOGOS);
    const { wrapper } = crearEntorno();

    const { result } = renderHook(() => useMetaCcaas(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(["MD", "CT"]);
  });

  it("NO dispara una segunda petición cuando convive con useMetaFilters", async () => {
    // El bug entero, en un test: las dos vistas montadas a la vez tienen que
    // producir una sola petición y una sola entrada de caché. `select` proyecta
    // sobre el dato ya cacheado; una clave propia lo duplicaría todo.
    const fetchMock = stub(CATALOGOS);
    const { client, wrapper } = crearEntorno();

    const { result } = renderHook(
      () => ({ filtros: useMetaFilters(), ccaas: useMetaCcaas() }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.filtros.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.ccaas.isSuccess).toBe(true));

    // Se cuenta por URL en vez de comparar el array entero: lo que este test
    // defiende es que NO hay una segunda petición al mismo endpoint, y una
    // igualdad exacta convierte cualquier ruido de otra consulta en un rojo que
    // no habla del bug. Igual con la caché: se filtra a las claves de `meta`.
    expect(fetchMock.mock.calls.map(callUrl).filter((u) => u === "/api/v1/meta/filters")).toHaveLength(
      1,
    );
    const clavesMeta = client
      .getQueryCache()
      .getAll()
      .map((query) => query.queryKey)
      .filter((clave) => Array.isArray(clave) && clave[0] === metaKeys.filters[0]);
    expect(clavesMeta).toEqual([metaKeys.filters]);
    // Y cada consumidor sigue viendo lo suyo: el catálogo entero y la
    // proyección, desde la misma entrada.
    expect(result.current.filtros.data).toEqual(CATALOGOS);
    expect(result.current.ccaas.data).toEqual(["MD", "CT"]);
  });

  it("una respuesta sin CCAA da una lista vacía, no un fallo de render", async () => {
    // `GET /meta/filters` no tiene DTO en el backend: si una dimensión llegara
    // ausente, `data.ccaa.map(...)` del consumidor reventaría la pantalla
    // entera. El `?? []` del `select` es lo que lo evita.
    stub({ estado: [], tecnologia: [], cpv: [] });
    const { wrapper } = crearEntorno();

    const { result } = renderHook(() => useMetaCcaas(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual([]);
  });
});
