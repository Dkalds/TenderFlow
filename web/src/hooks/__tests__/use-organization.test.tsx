/**
 * Qué organización queda activa cuando nadie ha elegido una.
 *
 * `GET /organizations` pone la personal primero. Quedarse con la primera dejaba
 * a un owner de equipo con Mi Pipeline y Dirección vacíos hasta que encontraba
 * el selector del menú de cuenta: el trabajo compartido vive en el equipo.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import {
  organizacionPorDefecto,
  useActiveOrganizationId,
  useOrganizationStore,
  type Organization,
} from "@/hooks/use-organization";
import { callUrl, jsonResponse } from "./fetch-call";

function org(id: number, is_personal: boolean): Organization {
  return {
    id,
    is_personal,
    name: is_personal ? "Personal" : `Equipo ${id}`,
    role: "owner",
    created_at: "2026-09-01T10:00:00Z",
  };
}

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function servirOrganizaciones(organizations: Organization[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((...call: unknown[]) =>
      Promise.resolve(jsonResponse(callUrl(call).includes("/organizations") ? organizations : {})),
    ),
  );
}

afterEach(() => {
  useOrganizationStore.setState({ activeOrganizationId: null });
  vi.unstubAllGlobals();
});

describe("organizacionPorDefecto", () => {
  it("prefiere la de equipo aunque la personal venga primero", () => {
    expect(organizacionPorDefecto([org(9, true), org(21, false)])).toBe(21);
  });

  it("con varios equipos toma el primero en el orden del servidor", () => {
    expect(organizacionPorDefecto([org(9, true), org(30, false), org(21, false)])).toBe(30);
  });

  it("sin equipo cae en la personal", () => {
    expect(organizacionPorDefecto([org(9, true)])).toBe(9);
  });

  it("sin organizaciones no inventa ninguna", () => {
    expect(organizacionPorDefecto([])).toBeNull();
  });
});

describe("useActiveOrganizationId", () => {
  it("sin elección guardada, arranca en el equipo", async () => {
    servirOrganizaciones([org(9, true), org(21, false)]);

    const { result } = renderHook(() => useActiveOrganizationId(), { wrapper });

    await waitFor(() => expect(result.current).toBe(21));
  });

  it("una elección guardada manda sobre el valor por defecto", async () => {
    useOrganizationStore.setState({ activeOrganizationId: 9 });
    servirOrganizaciones([org(9, true), org(21, false)]);

    const { result } = renderHook(() => useActiveOrganizationId(), { wrapper });

    await waitFor(() => expect(result.current).toBe(9));
  });

  it("una elección que ya no es de la persona no se respeta", async () => {
    // Sacaron a la persona del equipo 40: seguir mandándolo daría 403 en cada
    // pantalla con ámbito.
    useOrganizationStore.setState({ activeOrganizationId: 40 });
    servirOrganizaciones([org(9, true), org(21, false)]);

    const { result } = renderHook(() => useActiveOrganizationId(), { wrapper });

    await waitFor(() => expect(result.current).toBe(21));
  });
});
