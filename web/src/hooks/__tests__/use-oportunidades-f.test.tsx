/**
 * Hooks de F1.6 (etiquetas), F2.3 (kit), F4.3 (cartera) y F4.6 (plantilla de
 * tareas): qué pide cada uno, con qué organización, y qué hace con la caché.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { useOrganizationStore } from "@/hooks/use-organization";
import { useCambiarEtiqueta, useEtiquetasDe } from "@/hooks/use-etiquetas";
import { resumenKit, useAsignarKitItem, usePursuitKit } from "@/hooks/use-pursuit-kit";
import { useCartera } from "@/hooks/use-cartera";
import { filasATareas, tareasAFilas } from "@/hooks/use-plantilla-tareas";
import { pursuitKeys } from "@/lib/query-keys";
import { registrarEvento } from "@/lib/analytics";
import { callMethod, callUrl, jsonResponse } from "./fetch-call";

vi.mock("@/lib/analytics", () => ({
  registrarEvento: vi.fn(),
  tramoDeItems: vi.fn(() => "1-5"),
}));

const ORG = { id: 7, name: "Equipo", is_personal: false, role: "owner", created_at: "2026-09-18" };

function stub(respuesta: (url: string, method: string) => unknown) {
  const fetchMock = vi.fn().mockImplementation((...call: unknown[]) => {
    const url = callUrl(call);
    return Promise.resolve(
      jsonResponse(url.startsWith("/api/v1/organizations") ? [ORG] : respuesta(url, callMethod(call))),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function clienteYWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

const KIT = {
  licitacion_id: "L1",
  sin_extraccion: false,
  items: [
    { clave: "0:deuc", nombre: "DEUC", sobre: "sobre_a", listo: true },
    { clave: "1:garantia", nombre: "Garantía", sobre: "sobre_a", listo: false },
  ],
};

afterEach(() => {
  useOrganizationStore.setState({ activeOrganizationId: null });
  vi.unstubAllGlobals();
  vi.mocked(registrarEvento).mockClear();
});

describe("etiquetas (F1.6)", () => {
  it("pide las etiquetas de toda la lista en una sola petición y con la organización", async () => {
    useOrganizationStore.setState({ activeOrganizationId: 7 });
    const fetchMock = stub(() => ({ por_objeto: { "3": [{ id: 1, nombre: "Q4", color: "#64748b" }] } }));
    const { wrapper } = clienteYWrapper();

    const { result } = renderHook(() => useEtiquetasDe("oportunidad", ["3", "4", "3"]), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.["3"]?.[0].nombre).toBe("Q4");
    const llamadas = fetchMock.mock.calls.filter((c) => callUrl(c).includes("/etiquetas/por-objeto"));
    expect(llamadas).toHaveLength(1);
    expect(callUrl(llamadas[0])).toContain("organization_id=7");
    expect(JSON.parse(String((llamadas[0][1] as RequestInit).body))).toEqual({
      objeto_tipo: "oportunidad",
      objeto_ids: ["3", "4"],
    });
  });

  it("sin objetos no pide nada", async () => {
    const fetchMock = stub(() => ({}));
    const { wrapper } = clienteYWrapper();
    renderHook(() => useEtiquetasDe("favorito", []), { wrapper });
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchMock.mock.calls.some((c) => callUrl(c).includes("/etiquetas"))).toBe(false);
  });

  it("aplicar va a /aplicar y mide sólo el tipo de objeto; quitar va a /quitar y no mide", async () => {
    useOrganizationStore.setState({ activeOrganizationId: 7 });
    const fetchMock = stub(() => ({ cambiado: true }));
    const { wrapper } = clienteYWrapper();
    const { result } = renderHook(() => useCambiarEtiqueta(), { wrapper });

    await result.current.mutateAsync({ etiquetaId: 1, objetoTipo: "cuenta", objetoId: "9", aplicar: true });
    await result.current.mutateAsync({ etiquetaId: 1, objetoTipo: "cuenta", objetoId: "9", aplicar: false });

    const urls = fetchMock.mock.calls.map((c) => callUrl(c));
    expect(urls.some((u) => u.startsWith("/api/v1/etiquetas/aplicar"))).toBe(true);
    expect(urls.some((u) => u.startsWith("/api/v1/etiquetas/quitar"))).toBe(true);
    expect(registrarEvento).toHaveBeenCalledTimes(1);
    expect(registrarEvento).toHaveBeenCalledWith("etiqueta_aplicada", { objeto: "cuenta" });
  });
});

describe("kit de presentación (F2.3)", () => {
  it("carga el kit de la oportunidad con la organización activa", async () => {
    useOrganizationStore.setState({ activeOrganizationId: 7 });
    const fetchMock = stub(() => KIT);
    const { wrapper } = clienteYWrapper();

    const { result } = renderHook(() => usePursuitKit(3), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(resumenKit(result.current.data)).toEqual({ listos: 1, total: 2 });
    expect(fetchMock.mock.calls.some((c) => callUrl(c) === "/api/v1/pursuits/3/kit?organization_id=7")).toBe(true);
  });

  it("asignar siembra la caché con el kit devuelto e invalida la agenda", async () => {
    useOrganizationStore.setState({ activeOrganizationId: 7 });
    const asignado = {
      ...KIT,
      items: [{ ...KIT.items[1], tarea_id: 50, responsable_user_id: 42, responsable_name: "Ana" }],
    };
    const fetchMock = stub(() => asignado);
    const { client, wrapper } = clienteYWrapper();
    client.setQueryData([...pursuitKeys.agenda, {}, 7], { items: [] });

    const { result } = renderHook(() => useAsignarKitItem(3), { wrapper });
    await waitFor(() => expect(useOrganizationStore.getState().activeOrganizationId).toBe(7));
    await result.current.mutateAsync({ clave: "1:garantia", responsable_user_id: 42 });

    const post = fetchMock.mock.calls.find((c) => callUrl(c).includes("/kit/responsable"));
    expect(post && callMethod(post)).toBe("POST");
    expect(client.getQueryData(pursuitKeys.kit(3, 7))).toEqual(asignado);
    expect(client.getQueryState([...pursuitKeys.agenda, {}, 7])?.isInvalidated).toBe(true);
  });

  it("resumenKit sin kit es cero de cero", () => {
    expect(resumenKit(undefined)).toEqual({ listos: 0, total: 0 });
  });
});

describe("cartera (F4.3)", () => {
  it("manda la organización activa: sin ella el backend resuelve la personal", async () => {
    useOrganizationStore.setState({ activeOrganizationId: 7 });
    const fetchMock = stub(() => []);
    const { wrapper } = clienteYWrapper();

    const { result } = renderHook(() => useCartera(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(
      fetchMock.mock.calls.some((c) => callUrl(c) === "/api/v1/pursuits/cartera?organization_id=7"),
    ).toBe(true);
  });
});

describe("plantilla de tareas (F4.6)", () => {
  it("descarta filas sin título y convierte el plazo", () => {
    expect(
      filasATareas(
        [
          { titulo: " Revisión legal ", dias: "10" },
          { titulo: "", dias: "3" },
          { titulo: "Precio", dias: "" },
        ],
        20,
      ),
    ).toEqual({
      tareas: [
        { titulo: "Revisión legal", dias_antes_limite: 10 },
        { titulo: "Precio", dias_antes_limite: null },
      ],
      error: null,
    });
  });

  it("un plazo que no es número es un error, no «sin plazo»", () => {
    expect(filasATareas([{ titulo: "Precio", dias: "diez" }], 20).error).toMatch(/número de días/);
    expect(filasATareas([{ titulo: "Precio", dias: "400" }], 20).error).toMatch(/365/);
  });

  it("respeta el máximo", () => {
    const filas = Array.from({ length: 3 }, (_, i) => ({ titulo: `T${i}`, dias: "" }));
    expect(filasATareas(filas, 2).error).toMatch(/como mucho 2/);
  });

  it("ida y vuelta entre tareas y filas", () => {
    const tareas = [{ titulo: "A", dias_antes_limite: 5 }, { titulo: "B", dias_antes_limite: null }];
    expect(filasATareas(tareasAFilas(tareas), 20).tareas).toEqual(tareas);
  });
});
