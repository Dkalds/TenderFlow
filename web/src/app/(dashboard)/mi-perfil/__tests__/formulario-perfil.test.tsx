/**
 * Validación por esquema del perfil de scoring (`UserProfileBody`, S7.2).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/api-client", () => ({
  fetchWithAuth: vi.fn(),
  apiMutate: vi.fn(),
  apiGet: vi.fn().mockResolvedValue({
    estado: "insuficiente",
    n_cierres: 0,
    n_ganadas: 0,
    n_perdidas: 0,
    minimo_cierres: 20,
    organization_id: 7,
    origen_pesos_actuales: "global",
    pesos_actuales: {},
    dimensiones: [],
  }),
}));
vi.mock("@/lib/analytics", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/analytics")>();
  return { ...real, registrarEvento: vi.fn() };
});
vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => 7,
  useOrganizations: () => ({ data: [{ id: 7, name: "Equipo", role: "member" }] }),
}));

import MiPerfilPage from "@/app/(dashboard)/mi-perfil/page";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";

const mutar = vi.mocked(apiMutate);

function renderPagina() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <MiPerfilPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mutar.mockReset();
  mutar.mockResolvedValue({});
  vi.mocked(fetchWithAuth).mockResolvedValue({ importe_min: 1000, visibility: "organization" });
});
afterEach(() => cleanup());

describe("MiPerfilPage — esquema", () => {
  it("un rango al revés no se guarda y el error va bajo el máximo", async () => {
    renderPagina();
    await waitFor(() => expect(screen.getByLabelText("Mínimo (€)")).toHaveValue(1000));

    const maximo = screen.getByLabelText("Máximo (€)");
    fireEvent.change(maximo, { target: { value: "500" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar perfil" }));

    const error = await screen.findByText("El máximo no puede ser menor que el mínimo.");
    expect(error).toHaveAttribute("id", "mp-importe-max-error");
    expect(maximo).toHaveAttribute("aria-invalid", "true");
    expect(maximo).toHaveAttribute("aria-describedby", "mp-importe-max-error");
    expect(mutar).not.toHaveBeenCalled();

    // Corregido, revalida al escribir y guarda con las claves del DTO.
    fireEvent.change(maximo, { target: { value: "5000" } });
    await waitFor(() => expect(maximo).not.toHaveAttribute("aria-invalid"));
    fireEvent.click(screen.getByRole("button", { name: "Guardar perfil" }));
    await waitFor(() =>
      expect(mutar).toHaveBeenCalledWith(
        "PUT",
        "/api/v1/me/profile",
        expect.objectContaining({ importe_min: 1000, importe_max: 5000, visibility: "organization" }),
      ),
    );
  });

  it("los valores del servidor no cuentan como cambio: «Guardar» empieza apagado", async () => {
    renderPagina();
    await waitFor(() => expect(screen.getByLabelText("Mínimo (€)")).toHaveValue(1000));
    expect(screen.getByRole("button", { name: "Guardar perfil" })).toBeDisabled();
  });
});
