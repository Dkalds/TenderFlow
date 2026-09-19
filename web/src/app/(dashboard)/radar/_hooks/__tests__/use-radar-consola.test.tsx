import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import { withNuqsTestingAdapter } from "nuqs/adapters/testing";
import type { RadarTender } from "@/hooks/use-radar";
import { getJSON, setJSON } from "@/lib/storage";

/**
 * `useRadarConsola` sin árbol de render. El suite de `radar/__tests__/page.test.tsx`
 * prueba las acciones a través de la pantalla con `useFilters` doblado; aquí el
 * ámbito es el **real** (nuqs leyendo la URL) y se fija lo que la pantalla no
 * deja ver fácil: qué tecnología llega al ranking, los contadores de cada
 * bandeja, el orden, el recorte del índice activo y el sello de última visita.
 * Los hooks de datos se doblan: su contrato HTTP lo prueban
 * `hooks/__tests__/use-radar.test.tsx` y el prefetch del Radar.
 */

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(),
}));

const toastCall = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => {
  const toast = (...a: unknown[]) => toastCall(...a);
  toast.success = (...a: unknown[]) => toastSuccess(...a);
  toast.error = (...a: unknown[]) => toastError(...a);
  return { toast };
});

const estado = vi.hoisted(() => ({
  items: [] as RadarTender[],
  descartadas: [] as string[],
  seguidas: [] as string[],
  proximasTotal: 3 as number | null,
  tecnologiaPedida: undefined as string | null | undefined,
  descartadasPedidas: undefined as { ids: string[]; enabled: boolean } | undefined,
}));

const dismissMutate = vi.fn();
const restoreMutate = vi.fn();
vi.mock("@/hooks/use-radar", () => ({
  useRadar: (tecnologia: string | null) => {
    estado.tecnologiaPedida = tecnologia;
    return { data: { items: estado.items, signals: null }, isLoading: false, error: null, refetch: vi.fn() };
  },
  useRadarDismissals: () => ({ data: estado.descartadas }),
  useRadarDismissedTenders: (ids: string[], enabled: boolean) => {
    estado.descartadasPedidas = { ids, enabled };
    return {
      items: enabled ? estado.items.filter((t) => ids.includes(t.id_externo)) : [],
      isLoading: false,
      truncadas: 0,
    };
  },
  useDismissRadarTender: () => ({ mutate: dismissMutate }),
  useRestoreRadarTender: () => ({ mutate: restoreMutate }),
  esBandaConocida: (valor: unknown) => valor === "Caliente" || valor === "Tibia",
}));

const addWatchlist = vi.fn();
const removeWatchlist = vi.fn();
vi.mock("@/hooks/use-watchlist-items", () => ({
  useWatchlistItems: () => ({ data: estado.seguidas.map((id_externo) => ({ id_externo })) }),
  useAddWatchlistItem: () => ({ mutate: addWatchlist }),
  useRemoveWatchlistItem: () => ({ mutate: removeWatchlist }),
}));

const createPursuit = vi.fn();
vi.mock("@/hooks/use-pursuits", () => ({
  useCreatePursuit: () => ({ mutateAsync: createPursuit, isPending: false }),
}));

const setActiveOrganizationId = vi.fn();
vi.mock("@/hooks/use-organization", () => ({
  useOrganizationStore: (selector: (s: unknown) => unknown) => selector({ setActiveOrganizationId }),
}));

vi.mock("../use-radar-proximas", () => ({
  useRadarProximas: () => ({
    items: [],
    total: estado.proximasTotal,
    conFechaPrevista: null,
    estados: [],
    truncadas: 0,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
}));

import { useRadarConsola } from "../use-radar-consola";

function tender(id: string, overrides: Partial<RadarTender> = {}): RadarTender {
  return {
    id_externo: id,
    titulo: `Licitación ${id}`,
    score: 50,
    band: "Tibia",
    importe: 1000,
    fecha_limite: null,
    ...overrides,
  } as RadarTender;
}

function montar(search = "") {
  return renderHook(() => useRadarConsola(), { wrapper: withNuqsTestingAdapter({ searchParams: search }) });
}

const DIA = 86_400_000;
const enDias = (n: number) => new Date(Date.now() + n * DIA).toISOString();

beforeEach(() => {
  estado.items = [
    tender("A", { score: 60, importe: 10, fecha_limite: enDias(20) }),
    tender("B", { score: 90, importe: 30, fecha_limite: null }),
    tender("C", { score: 75, importe: 20, fecha_limite: enDias(2) }),
    tender("D", { score: 10, importe: 99 }),
  ];
  estado.descartadas = ["D"];
  estado.seguidas = ["C"];
  estado.proximasTotal = 3;
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("useRadarConsola", () => {
  it("el ranking se pide con la primera tecnología del ámbito de la URL", () => {
    montar("?tecnologia=SAP,Oracle&ccaa=MD");
    expect(estado.tecnologiaPedida).toBe("SAP");
  });

  it("sin tecnología en el ámbito el ranking es el global", () => {
    montar("?ccaa=MD");
    expect(estado.tecnologiaPedida).toBeNull();
  });

  it("cuenta cada bandeja: la bandeja excluye descartadas y seguidas", () => {
    const { result } = montar();
    expect(result.current.counts).toEqual({
      bandeja: 2,
      proximas: 3,
      siguiendo: 1,
      descartadas: 1,
      todas: 4,
    });
    expect(result.current.rows.map((r) => r.id_externo)).toEqual(["B", "A"]);
  });

  it("«Próximas» sin dato dice null, no cero", () => {
    estado.proximasTotal = null;
    const { result } = montar();
    expect(result.current.counts.proximas).toBeNull();
  });

  it("ordena por plazo (sin plazo al final) y por importe", () => {
    const { result } = montar();
    act(() => result.current.setSegment("todas"));
    expect(result.current.rows.map((r) => r.id_externo)).toEqual(["B", "C", "A"]);

    act(() => result.current.setSort("plazo"));
    expect(result.current.rows.map((r) => r.id_externo)).toEqual(["C", "A", "B"]);

    act(() => result.current.setSort("importe"));
    expect(result.current.rows.map((r) => r.id_externo)).toEqual(["B", "C", "A"]);
  });

  it("cambiar de bandeja vuelve a la primera fila, y el índice activo nunca se sale", () => {
    const { result } = montar();
    act(() => result.current.setSelected(1));
    expect(result.current.active?.id_externo).toBe("A");

    act(() => result.current.setSegment("siguiendo"));
    expect(result.current.selected).toBe(0);
    expect(result.current.rows.map((r) => r.id_externo)).toEqual(["C"]);

    act(() => result.current.setSelected(7));
    expect(result.current.activeIndex).toBe(0);
    expect(result.current.active?.id_externo).toBe("C");
  });

  it("las descartadas se hidratan aparte y sólo con su bandeja abierta", () => {
    const { result } = montar();
    expect(estado.descartadasPedidas).toEqual({ ids: ["D"], enabled: false });

    act(() => result.current.setSegment("descartadas"));
    expect(estado.descartadasPedidas).toEqual({ ids: ["D"], enabled: true });
    expect(result.current.rows.map((r) => r.id_externo)).toEqual(["D"]);
  });

  it("«Próximas» no devuelve filas de ranking: las pinta su propia bandeja", () => {
    const { result } = montar();
    act(() => result.current.setSegment("proximas"));
    expect(result.current.rows).toEqual([]);
    expect(result.current.active).toBeUndefined();
  });

  it("descartar sella score y banda conocida; una banda desconocida viaja como null", () => {
    const { result } = montar();
    act(() => result.current.dismiss(tender("X", { score: 42, band: "Inventada" as RadarTender["band"] })));
    expect(dismissMutate).toHaveBeenCalledWith({ idExterno: "X", score: 42, banda: null });

    act(() => result.current.dismiss(tender("Y", { score: 88, band: "Caliente" })));
    expect(dismissMutate).toHaveBeenLastCalledWith({ idExterno: "Y", score: 88, banda: "Caliente" });
  });

  it("el triaje lleva si se abrió la explicación del score de esa señal (F1.3)", () => {
    const { result } = montar();
    act(() => result.current.marcarExplicacion(tender("LEIDA")));
    act(() => result.current.aplazar(tender("LEIDA", { score: 60, band: "Tibia" }), "silenciar", 30));
    expect(dismissMutate).toHaveBeenLastCalledWith({
      idExterno: "LEIDA",
      score: 60,
      banda: "Tibia",
      explicacionAbierta: true,
      accion: "silenciar",
      dias: 30,
    });
    // Otra señal sin explicación abierta no la hereda.
    act(() => result.current.dismiss(tender("OTRA", { score: 50, band: "Tibia" })));
    expect(dismissMutate).toHaveBeenLastCalledWith({ idExterno: "OTRA", score: 50, banda: "Tibia" });
  });

  it("restaurar todo restaura cada descartada", () => {
    estado.descartadas = ["D", "A"];
    const { result } = montar();
    act(() => result.current.restoreAll());
    expect(restoreMutate.mock.calls.map((c) => c[0])).toEqual(["D", "A"]);
    expect(result.current.dismissedCount).toBe(2);
  });

  it("seguir y dejar de seguir alternan según el estado real de la watchlist", () => {
    const { result } = montar();
    act(() => result.current.toggleFollow(tender("C")));
    expect(removeWatchlist).toHaveBeenCalledWith("C");
    act(() => result.current.toggleFollow(tender("A")));
    expect(addWatchlist).toHaveBeenCalledWith("A");
  });

  it("abrir oportunidad cambia a su organización y navega; si falla, lo dice", async () => {
    createPursuit.mockResolvedValueOnce({ id: 12, organization_id: 4 });
    const { result } = montar();
    await act(() => result.current.openPursuit(tender("B", { score: 90, band: "Caliente" })));
    expect(createPursuit).toHaveBeenCalledWith({
      licitacion_id: "B",
      score_al_abrir: 90,
      banda_al_abrir: "Caliente",
    });
    expect(setActiveOrganizationId).toHaveBeenCalledWith(4);
    expect(push).toHaveBeenCalledWith("/oportunidades/12");

    createPursuit.mockRejectedValueOnce(new Error("Sin permisos en la organización"));
    await act(() => result.current.openPursuit(tender("A")));
    expect(toastError).toHaveBeenCalledWith("Sin permisos en la organización");
  });

  it("lee la última visita al montar y la reescribe al salir", () => {
    setJSON("radar-last-visit", 1234);
    const { result, unmount } = montar();
    expect(result.current.lastVisit).toBe(1234);

    unmount();
    expect(getJSON<number>("radar-last-visit", 0)).toBeGreaterThan(1234);
  });
});
