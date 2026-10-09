import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider } from "@/lib/auth";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * La tira de salud de Ops: cuatro preguntas de guardia, cada una con su puerta.
 *
 * Tenía una celda que no era de salud («Etiquetas registradas», un acumulado
 * que solo crece), ninguna llevaba a donde se actúa, y de los pasos del cierre
 * —lo que de verdad se rompía— no decía nada.
 */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/ops",
  useSearchParams: () => new URLSearchParams(),
}));

import { OpsHealthStrip } from "../_components/health-strip";

const FUENTES = {
  sources: [],
  healthy_sources: 7,
  total_sources: 7,
  healthy_sources_pct: 100,
  generated_at: "2026-10-09T02:00:00+00:00",
};

const EJECUCIONES = {
  ventana_dias: 7,
  horizonte_dias: 90,
  pasos_en_error: 2,
  generado_at: "2026-10-09T02:00:00+00:00",
  pasos: Array.from({ length: 22 }, (_, i) => ({
    paso: `paso_${i}`,
    tier: "bloqueante",
    ultimo_estado: i < 2 ? "error" : "ok",
    fallos: 0,
    ejecuciones: 1,
  })),
  trabajos: [],
};

/** Una petición que no llega nunca: deja a quien la espera en «cargando». */
const colgada = () => new Promise<Response>(() => {});

function montar({
  admin = true,
  calidad = { dlq_count: 6, last_scrape_hours_ago: 30 } as unknown,
  calidadStatus = 200,
  calidadColgada = false,
  sesionColgada = false,
} = {}) {
  const fetchMock = vi.fn().mockImplementation((...call: unknown[]) => {
    const url = callUrl(call);
    if (url.startsWith("/api/v1/auth/me")) {
      if (sesionColgada) return colgada();
      return Promise.resolve(
        jsonResponse({ user_id: "1", email: "a@b.es", display_name: "A", is_admin: admin }),
      );
    }
    if (url.startsWith("/api/v1/analytics/source-freshness")) return Promise.resolve(jsonResponse(FUENTES));
    if (url.startsWith("/api/v1/analytics/quality")) {
      if (calidadColgada) return colgada();
      return Promise.resolve(jsonResponse(calidad, calidadStatus));
    }
    if (url.startsWith("/api/v1/admin/ejecuciones")) return Promise.resolve(jsonResponse(EJECUCIONES));
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SessionProvider>
        <OpsHealthStrip />
      </SessionProvider>
    </QueryClientProvider>,
  );
  return fetchMock;
}

/** La celda entera (es un enlace) a partir de su rótulo. */
async function celda(rotulo: string): Promise<HTMLElement> {
  const enlace = (await screen.findByText(rotulo)).closest("a");
  if (!enlace) throw new Error(`la celda «${rotulo}» no es un enlace`);
  return enlace;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("OpsHealthStrip", () => {
  it("cada celda lleva a la vista donde se actúa", async () => {
    montar();

    expect(await celda("Fuentes al día")).toHaveAttribute("href", "/ops?vista=calidad");
    expect(await celda("Última ingesta")).toHaveAttribute("href", "/ops?vista=calidad");
    expect(await celda("Cola de errores")).toHaveAttribute("href", "/ops?vista=ejecuciones");
    expect(await celda("Pasos del cierre")).toHaveAttribute("href", "/ops?vista=ejecuciones");
  });

  it("dice cuántos pasos del cierre están rotos", async () => {
    montar();

    const pasos = await celda("Pasos del cierre");
    expect(await within(pasos).findByText("2 con error")).toBeInTheDocument();
    expect(within(pasos).getByText("de 22, en su última ejecución")).toBeInTheDocument();
  });

  it("la ingesta atrasada se dice con su etiqueta", async () => {
    montar();

    const ingesta = await celda("Última ingesta");
    expect(await within(ingesta).findByText("Desfasada")).toBeInTheDocument();
  });

  it("sin recuento de la cola enseña una raya, no un cero", async () => {
    montar({ calidad: { detail: "boom" }, calidadStatus: 500 });

    const cola = await celda("Cola de errores");
    expect(await within(cola).findByText("sin dato")).toBeInTheDocument();
    expect(within(cola).queryByText("0")).not.toBeInTheDocument();
  });

  it("no cuenta etiquetas: un acumulado no es una señal de salud", async () => {
    montar();

    await celda("Fuentes al día");
    expect(screen.queryByText("Etiquetas registradas")).not.toBeInTheDocument();
  });

  it("sin permisos de administrador no pide ni pinta los pasos del cierre", async () => {
    const fetchMock = montar({ admin: false });

    await celda("Cola de errores");
    await waitFor(() => expect(screen.queryByText("Pasos del cierre")).not.toBeInTheDocument());
    expect(fetchMock.mock.calls.some((c) => callUrl(c).includes("/admin/ejecuciones"))).toBe(false);
  });

  it("mientras llega el dato no dice «sin dato»: todavía no se sabe", async () => {
    // «Sin dato» es una respuesta —la consulta falló o no midió—, no el estado
    // de una consulta que sigue en vuelo.
    montar({ calidadColgada: true });

    const cola = await celda("Cola de errores");
    expect(within(cola).queryByText("sin dato")).not.toBeInTheDocument();
    expect(within(await celda("Última ingesta")).queryByText("sin dato")).not.toBeInTheDocument();
  });

  it("mientras se resuelve la sesión reserva la celda de los pasos sin pedir nada", async () => {
    // Para quien entra en Ops —un administrador— la tira no debe pasar de tres
    // columnas a cuatro al llegar la sesión.
    const fetchMock = montar({ sesionColgada: true });

    await celda("Pasos del cierre");
    expect(fetchMock.mock.calls.some((c) => callUrl(c).includes("/admin/ejecuciones"))).toBe(false);
  });
});
