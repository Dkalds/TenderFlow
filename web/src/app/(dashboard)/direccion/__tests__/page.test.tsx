/**
 * Dirección pide el cuadro de la organización activa, no el de la personal.
 *
 * Sin `organization_id` el backend resuelve la organización personal, y las
 * oportunidades viven en la del equipo: la pantalla salía con «Sin cierres»
 * para un owner que en la Agenda sí veía sus oportunidades.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { apiGet, ApiError, vista } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  vista: { actual: "resultado" },
  ApiError: class ApiError extends Error {
    constructor(
      public status: number,
      message: string,
    ) {
      super(message);
    }
  },
}));

vi.mock("@/lib/api-client", () => ({ apiGet, ApiError }));
vi.mock("@/hooks/use-organization", () => ({
  // Réplica de la real: `undefined` es «todavía no se sabe»; `null`, «no hay
  // ninguna», que sí es una respuesta y deja pasar la consulta.
  organizacionResuelta: (id: unknown) => id !== undefined,
  useActiveOrganizationId: () => 21,
  useOrganizationMembers: () => ({ data: [] }),
}));
vi.mock("@/components/layout/space-shell", () => ({
  useSpaceView: () => ({ view: vista.actual, setView: vi.fn() }),
  SpaceShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

import DireccionPage from "@/app/(dashboard)/direccion/page";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <DireccionPage />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  apiGet.mockReset();
  vista.actual = "resultado";
});

describe("DireccionPage", () => {
  it("pide el cuadro de la organización activa", async () => {
    apiGet.mockResolvedValue({
      organization_id: 21,
      n_minimo: 5,
      win_rate_por_tecnologia: [],
      win_rate_por_organo: [],
    });

    renderPage();

    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(apiGet).toHaveBeenCalledWith("/api/v1/pursuits/direccion", {
      params: { query: { organization_id: 21 } },
    });
  });

  it("publica el win rate desde el mínimo y enseña el hueco por debajo", async () => {
    apiGet.mockResolvedValue({
      organization_id: 21,
      n_minimo: 5,
      win_rate_por_tecnologia: [{ clave: "SAP", n: 8, valor: 0.25 }],
      win_rate_por_organo: [{ clave: "Ayuntamiento de Madrid", n: 1, valor: null }],
    });

    renderPage();

    expect(await screen.findByText("SAP")).toBeTruthy();
    expect(screen.getByText("25 %")).toBeTruthy();
    expect(screen.getByText("Ayuntamiento de Madrid")).toBeTruthy();
    expect(screen.getByText("aún no (1/5)")).toBeTruthy();
  });

  it("pinta las tarjetas con su cifra y, sin base, la nota en vez de un número", async () => {
    apiGet.mockResolvedValue({
      organization_id: 21,
      n_minimo: 5,
      win_rate_por_tecnologia: [],
      win_rate_por_organo: [],
      perdidas_n_minimo: 5,
      perdidas_por_motivo: [{ motivo: "precio", n: 4, pct: 0.8 }],
      radar_quality: null,
      tarjetas: [
        {
          clave: "valor_ponderado",
          etiqueta: "Valor ponderado del pipeline",
          valor: 50000,
          unidad: "eur",
          n: 3,
          n_minimo: 1,
          universo: "Oportunidades abiertas hoy.",
          nota: null,
        },
        {
          clave: "ciclo_dias",
          etiqueta: "Ciclo de identificada a cerrada (mediana)",
          valor: null,
          unidad: "dias",
          n: 2,
          n_minimo: 5,
          universo: "Ganadas o perdidas.",
          nota: "Sin base: 2 cierre(s) con fechas; hacen falta 5.",
        },
      ],
    });

    renderPage();

    expect(await screen.findByText("Valor ponderado del pipeline")).toBeTruthy();
    expect(screen.getByText(/50\.000\s€/)).toBeTruthy();
    expect(screen.getByText("Sin base")).toBeTruthy();
    expect(screen.getByText("Sin base: 2 cierre(s) con fechas; hacen falta 5.")).toBeTruthy();
    expect(screen.getByText(/n = 2 \(mínimo 5\)/)).toBeTruthy();
    expect(screen.getByText("Precio")).toBeTruthy();
    expect(screen.getByText("80 %")).toBeTruthy();
  });

  it("un 403 se explica como rol, no como caída", async () => {
    apiGet.mockRejectedValue(new ApiError(403, "Forbidden"));

    renderPage();

    expect(await screen.findByText("Dirección es para owner y admin")).toBeTruthy();
  });

  it("la vista Actividad pide el feed del equipo, no un texto que manda al Resumen", async () => {
    vista.actual = "actividad";
    apiGet.mockImplementation((path: string) =>
      Promise.resolve(
        path === "/api/v1/pursuits/actividad"
          ? { organization_id: 21, items: [], siguiente_cursor: null, filtrado_por_rol: false }
          : { organization_id: 21, n_minimo: 5, win_rate_por_tecnologia: [], win_rate_por_organo: [] },
      ),
    );

    renderPage();

    expect(await screen.findByText("Sin actividad")).toBeTruthy();
    expect(apiGet).toHaveBeenCalledWith(
      "/api/v1/pursuits/actividad",
      expect.objectContaining({ params: { query: expect.objectContaining({ organization_id: 21 }) } }),
    );
  });
});
