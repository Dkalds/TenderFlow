import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { callMethod, callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";
import { crearQueryClientDePrueba } from "@/test/query-client";
import type { ApiRule, MatchItem } from "../watchlist-rule-types";

/**
 * El estado de Mi Watchlist sin pintar la página: el aviso de la baja de
 * correos, qué coincidencias se piden (solo de reglas activas, y una regla que
 * falla no se lleva a las demás) y que editar solo cierra el panel si el PUT
 * fue bien.
 */

vi.mock("next/navigation", () => import("@/test/navegacion-superficial"));

const toastInfo = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    info: (...a: unknown[]) => toastInfo(...a),
    // El PUT fallido avisa por el aviso global de mutaciones.
    error: (...a: unknown[]) => toastError(...a),
  }),
}));
vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn(), primeraVez: () => true }));

import { irA, router } from "@/test/navegacion-superficial";
import { useMiWatchlist } from "../use-mi-watchlist";

function regla(id: number, active: boolean): ApiRule {
  return {
    id,
    nombre: `Regla ${id}`,
    keyword: "sap",
    cpv: null,
    min_importe: null,
    ccaa: null,
    frequency: "daily",
    active,
    match_count: 0,
    email: null,
    visibility: "private",
  } as ApiRule;
}

function coincidencia(id: string): MatchItem {
  return {
    id_externo: id,
    titulo: `Expediente ${id}`,
    ccaa: null,
    cpv: null,
    estado: null,
    fecha_publicacion: null,
    importe: null,
    organo_contratacion: null,
    url: null,
  };
}

let fetchMock: ReturnType<typeof vi.fn>;
let putOk = true;

beforeEach(() => {
  vi.clearAllMocks();
  irA("/mi-watchlist");
  putOk = true;
  fetchMock = vi.fn().mockImplementation((...call: unknown[]) => {
    const url = callUrl(call);
    const metodo = callMethod(call);
    if (metodo === "PUT") return Promise.resolve(jsonResponse({}, putOk ? 200 : 500));
    if (url === "/api/v1/watchlist/rules") {
      return Promise.resolve(jsonResponse({ items: [regla(1, true), regla(2, false), regla(3, true)] }));
    }
    if (url.startsWith("/api/v1/watchlist/rules/1/matches")) {
      return Promise.resolve(jsonResponse({ items: [coincidencia("A"), coincidencia("B")], total: 2 }));
    }
    if (url.startsWith("/api/v1/watchlist/rules/3/matches")) {
      return Promise.resolve(jsonResponse({ detail: "boom" }, 500));
    }
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function montar() {
  const client = crearQueryClientDePrueba();
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useMiWatchlist(), { wrapper });
}

describe("useMiWatchlist", () => {
  it("al volver de la baja de correos avisa de cuántas reglas se pausaron y limpia la URL", async () => {
    irA("/mi-watchlist?baja=3");
    montar();
    await waitFor(() => expect(toastInfo).toHaveBeenCalledTimes(1));
    expect(toastInfo.mock.calls[0][0]).toContain("3 regla(s) en pausa");
    expect(router.replace).toHaveBeenCalledWith("/mi-watchlist", { scroll: false });
  });

  it("sin reglas que pausar lo dice en vez de inventarse un número", async () => {
    irA("/mi-watchlist?baja=0");
    montar();
    await waitFor(() => expect(toastInfo).toHaveBeenCalledWith("No había reglas activas que pausar."));
  });

  it("pide coincidencias solo de las reglas activas, y una que falla no tumba a las demás", async () => {
    const { result } = montar();
    await waitFor(() => expect(result.current.combined).toBeDefined());

    expect(result.current.ruleCount).toBe(3);
    expect(result.current.activeRules.map((r) => r.id)).toEqual([1, 3]);
    const pedidas = fetchMock.mock.calls.map((c) => callUrl(c)).filter((u) => u.includes("/matches"));
    expect(pedidas.some((u) => u.includes("/rules/2/"))).toBe(false);
    expect(result.current.combined?.map((m) => m.id_externo)).toEqual(["A", "B"]);
  });

  it("guardar la edición cierra el panel solo si el PUT fue bien", async () => {
    const { result } = montar();
    await waitFor(() => expect(result.current.rules).toBeDefined());
    const cuerpo = { ...regla(1, true) } as never;

    act(() => result.current.setEditingRule(regla(1, true)));
    putOk = false;
    act(() => result.current.saveEdit(1, cuerpo));
    await waitFor(() => expect(result.current.savingEdit).toBe(false));
    expect(result.current.editingRule?.id).toBe(1);
    expect(toastError).toHaveBeenCalledTimes(1);

    putOk = true;
    act(() => result.current.saveEdit(1, cuerpo));
    await waitFor(() => expect(result.current.editingRule).toBeNull());
  });

  it("«Nueva regla» sin palabra clave no crea nada", async () => {
    const { result } = montar();
    await waitFor(() => expect(result.current.rules).toBeDefined());

    act(() => result.current.nueva.submit());
    await waitFor(() => expect(result.current.nueva.form.formState.isSubmitted).toBe(true));
    expect(fetchMock.mock.calls.some((c) => callMethod(c) === "POST")).toBe(false);
  });
});
