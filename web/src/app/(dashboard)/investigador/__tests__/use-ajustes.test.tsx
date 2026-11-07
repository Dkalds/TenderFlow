/**
 * `useAjustes`: las consultas recientes son de la cuenta y el navegador solo
 * las cachea.
 *
 * Hasta 2026-11 vivían únicamente en `localStorage`, así que no viajaban a otro
 * dispositivo. Se fija que manda la lista del servidor, que apuntar una
 * consulta se ve al momento y se manda a la API, y que lo que recordaba el
 * navegador se sube una sola vez cuando la cuenta llega vacía.
 */

import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const apiGet = vi.hoisted(() => vi.fn());
const apiMutate = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api-client", () => ({ apiGet, apiMutate }));

const { useAjustes, arriba } = await import("../_hooks/use-ajustes");

const CACHE = "lsap:v1:search_history";
const SUBIDO = "lsap:v1:search_history_subido";

function montar() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={cliente}>{children}</QueryClientProvider>
  );
  return renderHook(() => useAjustes(), { wrapper });
}

function respuesta(consultas: string[]) {
  return Promise.resolve({ consultas });
}

beforeEach(() => {
  window.localStorage.clear();
  apiGet.mockReset();
  apiMutate.mockReset();
});
afterEach(cleanup);

describe("arriba", () => {
  it("sube la consulta sin repetirla y respeta el tope", () => {
    expect(arriba("b", ["a", "b", "c"])).toEqual(["b", "a", "c"]);
    expect(
      arriba(
        "nueva",
        Array.from({ length: 10 }, (_, i) => `c${i}`),
      ),
    ).toHaveLength(10);
  });
});

describe("useAjustes · consultas recientes", () => {
  it("manda la lista de la cuenta y la deja en la caché", async () => {
    window.localStorage.setItem(CACHE, JSON.stringify(["de este navegador"]));
    window.localStorage.setItem(SUBIDO, "true");
    apiGet.mockReturnValue(respuesta(["de la cuenta"]));

    const { result } = montar();

    await waitFor(() => expect(result.current.history).toEqual(["de la cuenta"]));
    expect(apiGet).toHaveBeenCalledWith("/api/v1/me/consultas-recientes");
    expect(JSON.parse(window.localStorage.getItem(CACHE) ?? "[]")).toEqual(["de la cuenta"]);
  });

  it("si la API no responde se queda la caché", async () => {
    window.localStorage.setItem(CACHE, JSON.stringify(["de este navegador"]));
    apiGet.mockRejectedValue(new Error("caída"));

    const { result } = montar();

    await waitFor(() => expect(result.current.lista).toBe(true));
    expect(result.current.history).toEqual(["de este navegador"]);
  });

  it("apuntar se ve al momento y va a la API", async () => {
    window.localStorage.setItem(SUBIDO, "true");
    apiGet.mockReturnValue(respuesta(["anterior"]));
    apiMutate.mockReturnValue(respuesta(["baja temeraria", "anterior"]));

    const { result } = montar();
    await waitFor(() => expect(result.current.history).toEqual(["anterior"]));

    act(() => result.current.addHistory("baja temeraria"));

    expect(result.current.history).toEqual(["baja temeraria", "anterior"]);
    await waitFor(() =>
      expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/me/consultas-recientes", {
        consulta: "baja temeraria",
      }),
    );
  });

  it("addHistory es estable entre renders", async () => {
    apiGet.mockReturnValue(respuesta([]));
    apiMutate.mockReturnValue(respuesta(["x"]));
    const { result, rerender } = montar();
    const primero = result.current.addHistory;

    act(() => result.current.addHistory("x"));
    rerender();

    expect(result.current.addHistory).toBe(primero);
  });

  it("la primera vez sube lo de este navegador, de la más antigua a la más reciente", async () => {
    window.localStorage.setItem(CACHE, JSON.stringify(["reciente", "antigua"]));
    apiGet.mockReturnValue(respuesta([]));
    apiMutate.mockReturnValueOnce(respuesta(["antigua"])).mockReturnValueOnce(respuesta(["reciente", "antigua"]));

    const { result } = montar();

    await waitFor(() => expect(apiMutate).toHaveBeenCalledTimes(2));
    expect(apiMutate.mock.calls.map((c) => c[2])).toEqual([{ consulta: "antigua" }, { consulta: "reciente" }]);
    await waitFor(() => expect(window.localStorage.getItem(SUBIDO)).toBe("true"));
    expect(result.current.history).toEqual(["reciente", "antigua"]);
  });

  it("no la vuelve a subir si ya se subió", async () => {
    window.localStorage.setItem(CACHE, JSON.stringify(["vieja"]));
    window.localStorage.setItem(SUBIDO, "true");
    apiGet.mockReturnValue(respuesta([]));

    const { result } = montar();

    await waitFor(() => expect(result.current.history).toEqual([]));
    expect(apiMutate).not.toHaveBeenCalled();
  });
});
