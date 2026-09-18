/**
 * Dirección pide el cuadro de la organización activa, no el de la personal.
 *
 * Sin `organization_id` el backend resuelve la organización personal, y las
 * oportunidades viven en la del equipo: la pantalla salía con «Sin cierres»
 * para un owner que en Mi Pipeline sí veía sus oportunidades.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { apiGet, ApiError } = vi.hoisted(() => ({
  apiGet: vi.fn(),
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
vi.mock("@/hooks/use-organization", () => ({ useActiveOrganizationId: () => 21 }));
vi.mock("@/components/layout/space-shell", () => ({
  useSpaceView: () => ({ view: "resultado", setView: vi.fn() }),
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

  it("un 403 se explica como rol, no como caída", async () => {
    apiGet.mockRejectedValue(new ApiError(403, "Forbidden"));

    renderPage();

    expect(await screen.findByText("Dirección es para owner y admin")).toBeTruthy();
  });
});
