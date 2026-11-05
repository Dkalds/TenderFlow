import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";
import { crearQueryClientDePrueba } from "@/test/query-client";
import type { OrganizacionActiva } from "@/hooks/use-organization";

/**
 * El cuadro de Dirección (CU-24): qué ventana pide según `?periodo=`, para qué
 * organización, y que cambiar el periodo reescribe la URL sin navegar.
 */

vi.mock("next/navigation", () => import("@/test/navegacion-superficial"));

import { irA, router } from "@/test/navegacion-superficial";
import { useCuadroDireccion } from "../use-cuadro-direccion";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  irA("/direccion");
  fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({})));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function montar(organizationId: OrganizacionActiva) {
  const client = crearQueryClientDePrueba();
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useCuadroDireccion(organizationId), { wrapper });
}

function pedida(): URL {
  const llamada = fetchMock.mock.calls.find((c) => callUrl(c).startsWith("/api/v1/pursuits/direccion"));
  if (!llamada) throw new Error("no se pidió el cuadro");
  return new URL(callUrl(llamada), "http://x");
}

describe("useCuadroDireccion", () => {
  it("entra por «12 meses»: pide desde hace un año, sin tope, para la organización activa", async () => {
    const { result } = montar(7);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.periodo).toBe("12m");
    const url = pedida();
    expect(url.searchParams.get("organization_id")).toBe("7");
    expect(url.searchParams.get("period_from")).toMatch(/^\d{4}-\d{2}-\d{2}/);
    expect(url.searchParams.has("period_to")).toBe(false);
  });

  it("con ?periodo=historico no acota la ventana", async () => {
    irA("/direccion?periodo=historico");
    const { result } = montar(7);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.periodo).toBe("historico");
    expect(pedida().searchParams.has("period_from")).toBe(false);
  });

  it("un ?periodo= que no existe cae en el de por defecto", () => {
    irA("/direccion?periodo=siempre");
    const { result } = montar(7);
    expect(result.current.periodo).toBe("12m");
  });

  it("no pide nada mientras no se sabe la organización", () => {
    montar(undefined);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sin organización de equipo (null) pide la personal, sin organization_id", async () => {
    const { result } = montar(null);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(pedida().searchParams.has("organization_id")).toBe(false);
  });

  it("cambiar el periodo reescribe ?periodo= sin navegar, y el de por defecto lo quita", async () => {
    const { result } = montar(7);

    act(() => result.current.cambiarPeriodo("anio"));
    await waitFor(() => expect(result.current.periodo).toBe("anio"));
    expect(window.location.search).toBe("?periodo=anio");

    act(() => result.current.cambiarPeriodo("12m"));
    await waitFor(() => expect(result.current.periodo).toBe("12m"));
    expect(window.location.search).toBe("");
    expect(router.push).not.toHaveBeenCalled();
    expect(router.replace).not.toHaveBeenCalled();
  });
});
