/**
 * Seguimiento de empresas: una consulta y una mutación compartidas.
 *
 * Antes de extraerlo, el par consulta+mutación de `["watchlist-empresas"]`
 * estaba copiado en `competidores/page.tsx`, `empresas/page.tsx` y
 * `components/competitors/company-profile.tsx`: misma clave de caché, tres
 * variantes de la lógica —dos aceptaban una lista de ids y una un id suelto— y
 * sólo una de las tres invalidaba la consulta al terminar. Compartir clave sin
 * compartir código es lo que deja que una copia derive de las otras.
 *
 * Lo que estos tests fijan es lo que el usuario nota: el icono de «siguiendo»
 * se pone al día solo, en todas las pantallas, después de alternar — y también
 * cuando la llamada falla, porque quedarse con el estado optimista de una
 * mutación que no ocurrió es peor que refrescar de más.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { useEmpresasWatchlist, useToggleEmpresaWatch } from "@/hooks/use-empresas-watchlist";
import { watchlistKeys } from "@/lib/query-keys";
import { callMethod, callUrl, jsonResponse } from "./fetch-call";

/** Un `QueryClient` estable por test (ver `use-meta-filters.test.tsx`). */
function crearEntorno() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, wrapper: Wrapper };
}

/**
 * `fetch` doblado. Por defecto el GET devuelve `seguidas` y las mutaciones
 * responden correctamente; `mutacion` permite forzar otra respuesta.
 */
function stubFetch(
  seguidas: readonly number[],
  mutacion: (call: readonly unknown[]) => Response | undefined = () => undefined,
) {
  const fetchMock = vi.fn().mockImplementation((...call: unknown[]) => {
    const forzada = mutacion(call);
    if (forzada) return Promise.resolve(forzada);
    if (callMethod(call) === "GET") {
      return Promise.resolve(
        jsonResponse({ items: seguidas.map((empresa_id) => ({ empresa_id })) }),
      );
    }
    if (callMethod(call) === "DELETE") return Promise.resolve(new Response(null, { status: 204 }));
    return Promise.resolve(jsonResponse({ ok: true }, 201));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useEmpresasWatchlist", () => {
  it("expone las empresas seguidas como conjunto de ids", async () => {
    // Las pantallas preguntan `watchedIds.has(id)` por cada fila del listado:
    // con un array sería una búsqueda lineal por fila.
    const fetchMock = stubFetch([7, 9]);
    const { wrapper } = crearEntorno();

    const { result } = renderHook(() => useEmpresasWatchlist(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.watchedIds).toEqual(new Set([7, 9]));
    expect(callUrl(fetchMock.mock.calls[0])).toBe("/api/v1/competitive/watchlist");
  });

  it("sin datos todavía, el conjunto está vacío en vez de indefinido", () => {
    // El primer render ocurre antes de que responda la API y las páginas ya
    // llaman `watchedIds.has(...)`: un `undefined` aquí sería una pantalla en
    // blanco por `TypeError`, no un estado de carga.
    stubFetch([]);
    const { wrapper } = crearEntorno();

    const { result } = renderHook(() => useEmpresasWatchlist(), { wrapper });

    expect(result.current.watchedIds).toEqual(new Set());
  });

  it("el conjunto conserva su identidad entre renders si el dato no cambió", async () => {
    // `watchedIds` se pasa como prop a las tarjetas y entra en dependencias de
    // efectos: un `new Set(...)` por render las haría re-renderizar siempre y
    // podría encadenar bucles de efectos.
    stubFetch([7]);
    const { wrapper } = crearEntorno();

    const { result, rerender } = renderHook(() => useEmpresasWatchlist(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const primero = result.current.watchedIds;
    rerender();

    expect(result.current.watchedIds).toBe(primero);
  });
});

describe("useToggleEmpresaWatch", () => {
  it("seguir manda un POST por empresa con la frecuencia por defecto", async () => {
    // El perfil de empresa alterna el grupo de `empresa_id` equivalentes que
    // dejó la deduplicación de la matriz: por eso el contrato es siempre una
    // lista, aunque el listado mande una sola.
    const fetchMock = stubFetch([]);
    const { wrapper } = crearEntorno();

    const { result } = renderHook(() => useToggleEmpresaWatch(), { wrapper });
    await result.current.mutateAsync({ empresaIds: [7, 9], watched: false });

    const posts = fetchMock.mock.calls.filter((call) => callMethod(call) === "POST");
    expect(posts.map(callUrl)).toEqual([
      "/api/v1/competitive/watchlist",
      "/api/v1/competitive/watchlist",
    ]);
    expect(posts.map((call) => JSON.parse(String((call[1] as RequestInit).body)))).toEqual([
      { empresa_id: 7, frequency: "daily" },
      { empresa_id: 9, frequency: "daily" },
    ]);
  });

  it("dejar de seguir manda un DELETE por empresa", async () => {
    const fetchMock = stubFetch([7, 9]);
    const { wrapper } = crearEntorno();

    const { result } = renderHook(() => useToggleEmpresaWatch(), { wrapper });
    await result.current.mutateAsync({ empresaIds: [7, 9], watched: true });

    const deletes = fetchMock.mock.calls.filter((call) => callMethod(call) === "DELETE");
    expect(deletes.map(callUrl)).toEqual([
      "/api/v1/competitive/watchlist/7",
      "/api/v1/competitive/watchlist/9",
    ]);
  });

  it("al terminar refresca la lista de seguidas, que es lo que pinta el icono", async () => {
    // La comprobación no es «se llamó a invalidateQueries» sino la consecuencia:
    // la consulta montada vuelve a pedir y el conjunto refleja el alta. Así el
    // test sigue valiendo si mañana la invalidación se hace de otra forma, y
    // deja de valer si se invalida una clave que no es la de la consulta —que
    // era precisamente el fallo de una de las tres copias.
    let seguidas: number[] = [];
    const fetchMock = stubFetch([], (call) => {
      if (callMethod(call) === "GET") {
        return jsonResponse({ items: seguidas.map((empresa_id) => ({ empresa_id })) });
      }
      seguidas = [...seguidas, 7];
      return jsonResponse({ ok: true }, 201);
    });
    const { wrapper } = crearEntorno();

    const { result } = renderHook(
      () => ({ lista: useEmpresasWatchlist(), toggle: useToggleEmpresaWatch() }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.lista.isSuccess).toBe(true));
    expect(result.current.lista.watchedIds).toEqual(new Set());

    await result.current.toggle.mutateAsync({ empresaIds: [7], watched: false });

    await waitFor(() => expect(result.current.lista.watchedIds).toEqual(new Set([7])));
    expect(fetchMock.mock.calls.filter((call) => callMethod(call) === "GET")).toHaveLength(2);
  });

  it("invalida exactamente la clave de la consulta de empresas seguidas", async () => {
    // Complemento del test anterior: fija *qué* clave se invalida, sin
    // observadores montados que la refresquen y borren la marca. Si alguien
    // cambiara la clave en un sitio y no en el otro, esto lo ve.
    stubFetch([]);
    const { client, wrapper } = crearEntorno();
    client.setQueryData(watchlistKeys.empresas, { items: [] });

    const { result } = renderHook(() => useToggleEmpresaWatch(), { wrapper });
    await result.current.mutateAsync({ empresaIds: [7], watched: false });

    await waitFor(() =>
      expect(
        client.getQueryCache().find({ queryKey: watchlistKeys.empresas, exact: true })?.state
          .isInvalidated,
      ).toBe(true),
    );
  });

  it("también refresca cuando la llamada falla", async () => {
    // `onSettled`, no `onSuccess`: si el alta se rechaza, la pantalla tiene que
    // volver al estado real del servidor. Con `onSuccess` el botón se quedaba
    // como estuviera hasta el siguiente refetch por tiempo.
    stubFetch([], (call) =>
      callMethod(call) === "POST" ? jsonResponse({ detail: "no se pudo" }, 500) : undefined,
    );
    const { client, wrapper } = crearEntorno();
    client.setQueryData(watchlistKeys.empresas, { items: [] });

    const { result } = renderHook(() => useToggleEmpresaWatch(), { wrapper });
    await expect(
      result.current.mutateAsync({ empresaIds: [7], watched: false }),
    ).rejects.toThrow("no se pudo");

    await waitFor(() =>
      expect(
        client.getQueryCache().find({ queryKey: watchlistKeys.empresas, exact: true })?.state
          .isInvalidated,
      ).toBe(true),
    );
  });
});
