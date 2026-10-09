import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider } from "@/lib/auth";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * El espacio Ops: cinco vistas, sus contadores y los `?vista=` que ya no son
 * vista propia.
 */

const consulta = vi.hoisted(() => ({ vista: null as string | null }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/ops",
  useSearchParams: () => new URLSearchParams(consulta.vista ? { vista: consulta.vista } : {}),
}));

// Cada vista tiene su propio test; aquí importa cuál se monta y con qué.
vi.mock("../_components/health-strip", () => ({ OpsHealthStrip: () => null }));
vi.mock("../_components/observabilidad-view", () => ({ default: () => <p>vista estado</p> }));
vi.mock("../_components/ejecuciones-view", () => ({ default: () => <p>vista ejecuciones</p> }));
vi.mock("../_components/calidad-datos-view", () => ({ default: () => <p>vista datos</p> }));
vi.mock("../_components/active-learning-view", () => ({ default: () => <p>vista etiquetado</p> }));
vi.mock("../_components/administracion-view", () => ({
  default: ({ ancla }: { ancla?: string }) => <p>vista administración{ancla ? ` en ${ancla}` : ""}</p>,
}));

import OpsPage from "../page";

function montar({ vista = null as string | null, admin = true } = {}) {
  consulta.vista = vista;
  const fetchMock = vi.fn().mockImplementation((...call: unknown[]) => {
    const url = callUrl(call);
    if (url.startsWith("/api/v1/auth/me")) {
      return Promise.resolve(
        jsonResponse({ user_id: "1", email: "a@b.es", display_name: "A", is_admin: admin }),
      );
    }
    if (url.startsWith("/api/v1/admin/ejecuciones")) {
      return Promise.resolve(
        jsonResponse({
          ventana_dias: 7,
          horizonte_dias: 90,
          pasos_en_error: 2,
          pasos: [],
          trabajos: [],
          generado_at: "2026-10-09T02:00:00+00:00",
        }),
      );
    }
    if (url.startsWith("/api/v1/admin/solicitudes-acceso")) {
      return Promise.resolve(
        jsonResponse([
          { id: 1, email: "a@x.es", estado: "pendiente" },
          { id: 2, email: "b@x.es", estado: "pendiente" },
          { id: 3, email: "c@x.es", estado: "pendiente" },
        ]),
      );
    }
    return Promise.resolve(jsonResponse({}));
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SessionProvider>
        <OpsPage />
      </SessionProvider>
    </QueryClientProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("OpsPage", () => {
  it("ofrece cinco vistas, en el orden del turno de guardia", async () => {
    montar();

    await screen.findByText("vista estado");
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent?.replace(/\s*\d+$/, ""))).toEqual([
      "Estado",
      "Ejecuciones",
      "Datos",
      "Etiquetado",
      "Administración",
    ]);
  });

  it("monta la vista que pide la URL", async () => {
    montar({ vista: "ejecuciones" });

    expect(await screen.findByText("vista ejecuciones")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Ejecuciones/ })).toHaveAttribute("aria-selected", "true");
  });

  it.each([
    ["flags", "feature-flags"],
    ["webhooks", "webhooks"],
  ])("el `?vista=%s` de antes aterriza en su sección de Administración", async (vista, ancla) => {
    montar({ vista });

    expect(await screen.findByText(`vista administración en ${ancla}`)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Administración/ })).toHaveAttribute("aria-selected", "true");
  });

  it("las pestañas con trabajo esperando llevan su recuento", async () => {
    montar();

    expect(await screen.findByRole("tab", { name: "Ejecuciones 2" })).toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: "Administración 3" })).toBeInTheDocument();
    // Sin nada esperando, la pestaña va sin número.
    expect(screen.getByRole("tab", { name: "Estado" })).toBeInTheDocument();
  });

  it("sin permisos de administrador no pide los recuentos", async () => {
    const fetchMock = montar({ admin: false });

    await screen.findByText("vista estado");
    const pedidas = fetchMock.mock.calls.map((c) => callUrl(c));
    expect(pedidas.some((url) => url.includes("/admin/"))).toBe(false);
    expect(screen.getByRole("tab", { name: "Ejecuciones" })).toBeInTheDocument();
  });
});
