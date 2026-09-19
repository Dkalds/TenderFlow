import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { withNuqsTestingAdapter } from "nuqs/adapters/testing";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * Calendario de vencimientos (RFC ux-calendario #2-#4).
 *
 * Fija que la vista principal pide los CIERRES del año elegido con el ámbito
 * de la URL, que los conteos del heatmap son los del backend (no un reparto
 * de otra serie, ADR-014), que hoy y los próximos 7 días van marcados, y que
 * cada día enlaza al listado exacto que cuenta.
 */

const searchParamsRef = vi.hoisted(() => ({ actual: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => searchParamsRef.actual }));

import {
  buildCalendarGrid,
  dayMapFromTrends,
  dayMapFromVencimientos,
  diaHref,
  dowFromDays,
  monthlyFromDays,
  useCalendarioView,
  type VencimientosResponse,
} from "../use-calendario-view";

const anio = new Date().getFullYear();

const VENCIMIENTOS: VencimientosResponse = {
  desde: `${anio}-01-01`,
  hasta: `${anio}-12-31`,
  dias: [
    { fecha: `${anio}-03-02`, count: 4, importe: 1000 },
    { fecha: `${anio}-03-09`, count: 1, importe: 50 },
  ],
  total: 5,
  dia_pico: { fecha: `${anio}-03-02`, count: 4, importe: 1000 },
  kpis: { hoy: `${anio}-03-01`, vencen_hoy: 0, vencen_7d: 4, vencen_resto_mes: 4 },
};

const TRENDS = { series: [{ period: `${anio}-05-05`, count: 9, importe: 10 }] };

function montar(search = "?ccaa=Galicia") {
  searchParamsRef.actual = new URLSearchParams(search);
  const fetchMock = vi.fn().mockImplementation((...call: unknown[]) => {
    const url = callUrl(call);
    return Promise.resolve(jsonResponse(url.includes("/calendario/vencimientos") ? VENCIMIENTOS : TRENDS));
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Nuqs = withNuqsTestingAdapter({ searchParams: search });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <Nuqs>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </Nuqs>
  );
  const hook = renderHook(() => useCalendarioView(), { wrapper });
  const urls = () => fetchMock.mock.calls.map((call) => new URL(callUrl(call), "http://x"));
  return { ...hook, urls };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("useCalendarioView", () => {
  it("la vista principal pide los cierres del año con el ámbito activo", async () => {
    const { result, urls } = montar();
    expect(result.current.modo).toBe("vencimientos");
    await waitFor(() => expect(result.current.vencimientos).toBeDefined());

    const pedida = urls().find((u) => u.pathname === "/api/v1/analytics/calendario/vencimientos")!;
    expect(pedida.searchParams.get("desde")).toBe(`${anio}-01-01`);
    expect(pedida.searchParams.get("hasta")).toBe(`${anio}-12-31`);
    expect(pedida.searchParams.get("ccaa")).toBe("Galicia");
    // La serie de publicaciones no se pide mientras no se mire.
    expect(urls().some((u) => u.pathname === "/api/v1/analytics/trends")).toBe(false);
  });

  it("el heatmap pinta el conteo real de cada día de cierre", async () => {
    const { result } = montar();
    await waitFor(() => expect(result.current.weeks.length).toBeGreaterThan(0));
    const celdas = result.current.weeks.flatMap((w) => w.days).filter((d) => d != null);
    expect(celdas.find((d) => d!.dateStr === `${anio}-03-02`)!.count).toBe(4);
    expect(celdas.find((d) => d!.dateStr === `${anio}-03-03`)!.count).toBe(0);
    expect(result.current.monthlyData).toEqual([{ mes: "Mar", count: 5, importe: 1050 }]);
  });

  it("el conmutador cambia a publicaciones y pide la serie diaria", async () => {
    const { result, urls } = montar();
    act(() => result.current.setModo("publicaciones"));
    await waitFor(() =>
      expect(urls().some((u) => u.pathname === "/api/v1/analytics/trends")).toBe(true),
    );
    const trends = urls().find((u) => u.pathname === "/api/v1/analytics/trends")!;
    expect(trends.searchParams.get("group_by")).toBe("day");
  });
});

describe("derivaciones del calendario", () => {
  it("marca hoy y los seis días siguientes, no el séptimo", () => {
    const dias = dayMapFromVencimientos(VENCIMIENTOS);
    const { weeks } = buildCalendarGrid(dias, 2026, new Date(2026, 2, 1));
    const celdas = weeks.flatMap((w) => w.days).filter((d) => d != null);
    const hoy = celdas.find((d) => d!.dateStr === "2026-03-01")!;
    expect(hoy.esHoy).toBe(true);
    expect(hoy.proximos7).toBe(true);
    expect(celdas.find((d) => d!.dateStr === "2026-03-07")!.proximos7).toBe(true);
    expect(celdas.find((d) => d!.dateStr === "2026-03-08")!.proximos7).toBe(false);
    expect(celdas.find((d) => d!.dateStr === "2026-02-28")!.proximos7).toBe(false);
  });

  it("la rejilla empieza en lunes y deja fuera los días de otro año", () => {
    const { weeks, months } = buildCalendarGrid(new Map(), 2026, new Date(2026, 5, 1));
    // 1-ene-2026 es jueves: lunes-miércoles de esa semana son de 2025.
    expect(weeks[0].days.slice(0, 3)).toEqual([null, null, null]);
    expect(weeks[0].days[3]!.dateStr).toBe("2026-01-01");
    expect(months[0].label).toBe("Ene");
  });

  it("cada día enlaza al listado de lo que cierra ese día", () => {
    expect(diaHref("2026-03-02")).toBe("/detalle?cierre_desde=2026-03-02&cierre_hasta=2026-03-02");
  });

  it("la serie de publicaciones descarta periodos que no son días", () => {
    const m = dayMapFromTrends([
      { period: "2026-01-05", count: 2, importe: 5 },
      { period: "2026-W02", count: 99, importe: 0 },
    ]);
    expect(Array.from(m.keys())).toEqual(["2026-01-05"]);
    expect(monthlyFromDays(m, 2026)).toEqual([{ mes: "Ene", count: 2, importe: 5 }]);
    // 5-ene-2026 es lunes.
    expect(dowFromDays(m, 2026)[0]).toEqual({ dia: "Lun", promedio: 2 });
  });
});
