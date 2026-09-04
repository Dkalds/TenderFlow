/**
 * Estadísticas de etiquetado (`GET /feedback/stats`).
 *
 * La consulta estaba copiada en `ops/_components/health-strip.tsx` y en
 * `ops/_components/active-learning-view.tsx`, cada una con su interfaz local de
 * la respuesta y su propio `staleTime`, bajo la misma clave. Las dos vistas se
 * montan a la vez en `/ops`: compartían caché sin compartir contrato, así que
 * la que ganara la carrera decidía cuándo se consideraba fresco el dato.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { useFeedbackStats } from "@/hooks/use-feedback";
import { feedbackKeys } from "@/lib/query-keys";
import { callUrl, jsonResponse } from "./fetch-call";

/** Un `QueryClient` estable por test (ver `use-meta-filters.test.tsx`). */
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

describe("useFeedbackStats", () => {
  it("pide las estadísticas a /feedback/stats", async () => {
    const fetchMock = stub({ total_labels: 120, pct_relevant: 0.42, last_updated: "2026-09-01" });
    const { wrapper } = crearEntorno();

    const { result } = renderHook(() => useFeedbackStats(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual({
      total_labels: 120,
      pct_relevant: 0.42,
      last_updated: "2026-09-01",
    });
    expect(fetchMock.mock.calls.map(callUrl)).toEqual(["/api/v1/feedback/stats"]);
  });

  it("las dos vistas de /ops comparten una sola petición", async () => {
    // Es la razón de existir del hook: la tira de salud y Active Learning se
    // montan juntas. Con la clave del registro comparten entrada de caché; con
    // dos literales iguales pero dos `queryFn` distintas —lo que había—
    // compartirían caché y no contrato, y ganaría la que montara primero.
    const fetchMock = stub({ total_labels: 5 });
    const { client, wrapper } = crearEntorno();

    const { result } = renderHook(
      () => ({ tira: useFeedbackStats(), aprendizaje: useFeedbackStats() }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.tira.isSuccess).toBe(true));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(client.getQueryCache().getAll().map((query) => query.queryKey)).toEqual([
      feedbackKeys.stats,
    ]);
    expect(result.current.aprendizaje.data).toEqual(result.current.tira.data);
  });

  it("un campo ausente llega como ausente, no como cero", async () => {
    // `GET /feedback/stats` devuelve un `dict` sin DTO en el backend, así que
    // el esquema generado no lo describe y todos los campos son opcionales a
    // propósito. La pantalla distingue «sin dato» de «cero»: rellenar el hueco
    // con 0 aquí haría que un backend que aún no calcula el porcentaje se
    // mostrara como 0% de relevantes, que es una afirmación falsa.
    stub({ total_labels: 0 });
    const { wrapper } = crearEntorno();

    const { result } = renderHook(() => useFeedbackStats(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.total_labels).toBe(0);
    expect(result.current.data?.pct_relevant).toBeUndefined();
    expect(result.current.data?.last_updated).toBeUndefined();
  });

  it("un fallo del endpoint se propaga como error, sin dato a medias", async () => {
    // La tira de salud pinta «sin dato» ante el error; si el hook devolviera un
    // objeto vacío como si fuera una respuesta, /ops afirmaría que hay cero
    // etiquetas cuando lo que hay es un backend caído.
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(jsonResponse({ detail: "caído" }, 503)));
    vi.stubGlobal("fetch", fetchMock);
    const { wrapper } = crearEntorno();

    const { result } = renderHook(() => useFeedbackStats(), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.data).toBeUndefined();
    expect(result.current.error).toMatchObject({ message: "caído" });
  });
});
