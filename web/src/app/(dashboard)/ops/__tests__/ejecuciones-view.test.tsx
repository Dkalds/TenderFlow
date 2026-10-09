import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider } from "@/lib/auth";
import { TooltipProvider } from "@/components/ui/tooltip";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * Ops › Ejecuciones: qué pasó con cada paso del cierre.
 *
 * La API guarda una fila por paso desde S5.4 y ninguna pantalla la leía: en
 * septiembre de 2026 un paso falló 62 pasadas seguidas y hubo que enterarse por
 * los logs de un runner. Aquí se comprueba que la vista dice lo que la fila
 * dice —y que un paso que no tocaba correr no se confunde con uno que falló.
 */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/ops",
  useSearchParams: () => new URLSearchParams(),
}));

import EjecucionesView from "../_components/ejecuciones-view";

const RESUMEN = {
  ventana_dias: 7,
  horizonte_dias: 90,
  pasos_en_error: 1,
  generado_at: "2026-10-09T02:00:00+00:00",
  pasos: [
    {
      paso: "ml_scoring",
      tier: "bloqueante",
      ultimo_estado: "error",
      ultima_ejecucion: "2026-10-08T21:44:00+00:00",
      ultima_ok: "2026-10-02T21:44:00+00:00",
      ultimo_fallo: "2026-10-08T21:44:00+00:00",
      ultimo_error: "ModelArtifactMismatch: el artefacto no coincide",
      fallos: 7,
      ejecuciones: 23,
    },
    {
      paso: "kpi_precompute",
      tier: "bloqueante",
      ultimo_estado: "ok",
      ultima_ejecucion: "2026-10-08T21:55:00+00:00",
      ultima_ok: "2026-10-08T21:55:00+00:00",
      ultimo_fallo: null,
      ultimo_error: null,
      fallos: 0,
      ejecuciones: 23,
    },
    {
      paso: "retention_cleanup",
      tier: "bloqueante",
      ultimo_estado: "omitido",
      ultima_ejecucion: "2026-10-08T21:57:00+00:00",
      ultima_ok: "2026-10-08T06:29:00+00:00",
      ultimo_fallo: null,
      ultimo_error: null,
      fallos: 0,
      ejecuciones: 6,
    },
    {
      paso: "drift_checks",
      tier: "advisory",
      ultimo_estado: "sin_ejecuciones",
      ultima_ejecucion: null,
      ultima_ok: null,
      ultimo_fallo: null,
      ultimo_error: null,
      fallos: 0,
      ejecuciones: 0,
    },
  ],
  trabajos: [
    {
      tipo: "ficha_pliego",
      pendientes: 2,
      en_curso: 1,
      fallidos: 11,
      hechos: 40,
      ultimo_fallo: "2026-10-05T15:40:00+00:00",
      ultimo_error: "RuntimeError: La licitación no referencia ningún pliego descargable",
    },
  ],
};

const DLQ = { estado: "abiertas", items: [], resumen: [], resumen_errores: [] };

function montar({ admin = true, resumen = RESUMEN as unknown, status = 200 } = {}) {
  const fetchMock = vi.fn().mockImplementation((...call: unknown[]) => {
    const url = callUrl(call);
    if (url.startsWith("/api/v1/auth/me")) {
      return Promise.resolve(
        jsonResponse({ user_id: "1", email: "a@b.es", display_name: "A", is_admin: admin }),
      );
    }
    if (url.startsWith("/api/v1/admin/ejecuciones")) {
      return Promise.resolve(jsonResponse(resumen, status));
    }
    if (url.startsWith("/api/v1/admin/dlq")) return Promise.resolve(jsonResponse(DLQ));
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SessionProvider>
        <TooltipProvider>
          <EjecucionesView />
        </TooltipProvider>
      </SessionProvider>
    </QueryClientProvider>,
  );
  return fetchMock;
}

function fila(paso: string): HTMLElement {
  const celda = screen.getByText(paso);
  const tr = celda.closest("tr");
  if (!tr) throw new Error(`sin fila para ${paso}`);
  return tr;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Ops › Ejecuciones", () => {
  it("el paso que falló enseña su error y cuántas veces en la ventana", async () => {
    montar();

    await screen.findByText("ml_scoring");
    const roto = fila("ml_scoring");
    expect(within(roto).getByText("Error")).toBeInTheDocument();
    expect(within(roto).getByText(/ModelArtifactMismatch: el artefacto no coincide/)).toBeInTheDocument();
    expect(within(roto).getByText("7 de 23")).toBeInTheDocument();
  });

  it("un paso que no tocaba correr no es un fallo", async () => {
    montar();

    await screen.findByText("retention_cleanup");
    const omitido = fila("retention_cleanup");
    expect(within(omitido).getByText("No tocaba")).toBeInTheDocument();
    expect(within(omitido).queryByText("Error")).not.toBeInTheDocument();
  });

  it("un paso sin ninguna fila se dice, no se omite", async () => {
    montar();

    await screen.findByText("drift_checks");
    expect(within(fila("drift_checks")).getByText("Sin ejecuciones")).toBeInTheDocument();
  });

  it("resume arriba cuántos pasos están rotos ahora", async () => {
    montar();

    expect(await screen.findByText("1 paso falló en su última ejecución")).toBeInTheDocument();
  });

  it("con todo en orden lo dice sin alarma", async () => {
    const sano = {
      ...RESUMEN,
      pasos_en_error: 0,
      pasos: RESUMEN.pasos.filter((p) => p.ultimo_estado !== "error"),
    };
    montar({ resumen: sano });

    expect(await screen.findByText("Ningún paso falló en su última ejecución")).toBeInTheDocument();
  });

  it("enseña la cola de trabajos a demanda con su último fallo", async () => {
    montar();

    const trabajo = (await screen.findByText("Ficha del pliego")).closest("tr");
    expect(trabajo).not.toBeNull();
    expect(within(trabajo as HTMLElement).getByText("11")).toBeInTheDocument();
    expect(
      within(trabajo as HTMLElement).getByText(/no referencia ningún pliego descargable/),
    ).toBeInTheDocument();
  });

  it("con la consulta caída dice que falló, no que no hay pasos", async () => {
    montar({ resumen: { detail: "boom" }, status: 500 });

    expect(await screen.findByText("No se pudieron cargar las ejecuciones")).toBeInTheDocument();
    expect(screen.queryByText(/Ningún paso falló/)).not.toBeInTheDocument();
  });

  it("no monta nada ni pide nada para quien no es administrador", async () => {
    const fetchMock = montar({ admin: false });

    expect(await screen.findByText("Acceso restringido")).toBeInTheDocument();
    const pedidas = fetchMock.mock.calls.map((c) => callUrl(c));
    expect(pedidas.every((url) => url === "/api/v1/auth/me")).toBe(true);
  });
});
