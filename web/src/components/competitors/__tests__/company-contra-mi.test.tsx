/**
 * F3.2 — la pestaña «Contra mí».
 *
 * Lo que fija: la petición lleva la organización activa y la ventana; «ganaron
 * ellos» y «perdimos» se pintan como cosas distintas (que es todo el sentido de
 * `resultado`); una fila sin nuestro precio lo dice; sin NIF propio la
 * pestaña avisa de lo que no se puede afirmar; y una ficha agrupada cruza todas
 * sus identidades, lo que la pestaña sólo afirma si el backend lo declara.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { fetchWithAuth } = vi.hoisted(() => ({ fetchWithAuth: vi.fn() }));

vi.mock("@/lib/api-client", () => ({ fetchWithAuth }));
vi.mock("@/hooks/use-organization", () => ({
  // Réplica de la real: `undefined` es «todavía no se sabe»; `null`, «no hay
  // ninguna», que sí es una respuesta y deja pasar la consulta.
  organizacionResuelta: (id: unknown) => id !== undefined,
  useActiveOrganizationId: () => 21,
}));

import { CompanyContraMi } from "../company-contra-mi";

function renderPestana(empresaIds?: number[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <CompanyContraMi empresaKey="42" empresaIds={empresaIds} />
    </QueryClientProvider>,
  );
}

const BATALLAS = {
  empresa_key: "42",
  n: 3,
  ventana: "últimos 24 meses",
  sin_nif_propio: false,
  batallas: [
    {
      licitacion_id: "ES-1",
      titulo: "Soporte SAP S/4HANA",
      organo_contratacion: "Ayuntamiento de Madrid",
      fecha: "2026-05-01",
      importe: 200000,
      resultado: "ellos_ganaron",
      nuestra_baja: 0.1,
      baja_ganadora: 0.15,
    },
    {
      licitacion_id: "ES-2",
      titulo: "Mantenimiento SAP",
      organo_contratacion: null,
      fecha: null,
      importe: null,
      resultado: "perdimos",
      nuestra_baja: null,
      baja_ganadora: null,
    },
    {
      licitacion_id: "ES-3",
      titulo: "Migración SAP",
      organo_contratacion: "Diputación",
      fecha: "2026-02-01",
      importe: 100000,
      resultado: "ganamos",
      nuestra_baja: 0.2,
      baja_ganadora: 0.2,
    },
  ],
};

afterEach(() => {
  cleanup();
  fetchWithAuth.mockReset();
});

describe("CompanyContraMi", () => {
  it("pide los cruces de la organización activa y separa «ganaron ellos» de «perdimos»", async () => {
    fetchWithAuth.mockResolvedValue(BATALLAS);
    renderPestana();

    expect(await screen.findByText("Soporte SAP S/4HANA")).toBeInTheDocument();
    expect(fetchWithAuth).toHaveBeenCalledWith(
      "/api/v1/competitive/empresas/42/contra-mi?meses=24&organization_id=21",
    );
    expect(screen.getByText("Ganaron ellos")).toBeInTheDocument();
    expect(screen.getByText("Perdimos")).toBeInTheDocument();
    expect(screen.getByText("Ganamos")).toBeInTheDocument();
    // La fila sin nuestro precio lo dice, y el resumen lo cuenta.
    expect(screen.getByText("Sin precio registrado")).toBeInTheDocument();
    expect(screen.getByText(/en 1 no registrasteis vuestro precio/)).toBeInTheDocument();
    // Bajas en tanto por uno → porcentaje.
    expect(screen.getByText("10,0%")).toBeInTheDocument();
    expect(screen.getByText("15,0%")).toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("sin NIF propio avisa de lo que no se puede afirmar", async () => {
    fetchWithAuth.mockResolvedValue({ ...BATALLAS, sin_nif_propio: true });
    renderPestana();

    expect(await screen.findByRole("note")).toHaveTextContent(/no ha declarado su NIF/);
    expect(screen.getByRole("link", { name: /Declararlo en Equipo/ })).toHaveAttribute("href", "/equipo");
  });

  it("un cierre perdido adjudicado a nuestro NIF se señala y no cuenta como derrota", async () => {
    fetchWithAuth.mockResolvedValue({
      ...BATALLAS,
      contradicciones: 1,
      batallas: [
        ...BATALLAS.batallas.slice(0, 2),
        { ...BATALLAS.batallas[2], resultado: "sin_resolver", contradiccion: true },
      ],
    });
    renderPestana();

    expect(await screen.findByRole("note")).toHaveTextContent(/aparece adjudicado a vuestro NIF/);
    expect(screen.getByText("Cerrado perdido, adjudicado a vosotros")).toBeInTheDocument();
    expect(screen.getByText("Sin resolver")).toBeInTheDocument();
  });

  it("una ficha agrupada manda el grupo y dice que cruza todas sus identidades", async () => {
    fetchWithAuth.mockResolvedValue({ ...BATALLAS, claves: ["42", "43"] });
    renderPestana([42, 43]);

    expect(await screen.findByText("Cruza las 2 identidades del maestro que suma esta ficha.")).toBeInTheDocument();
    const url = new URL(fetchWithAuth.mock.calls[0][0] as string, "http://x");
    expect(url.pathname).toBe("/api/v1/competitive/empresas/42/contra-mi");
    expect(url.searchParams.get("empresa_ids")).toBe("42,43");
  });

  it("si el backend no declara el grupo, la pestaña no lo afirma", async () => {
    // Un backend anterior a `claves` ignora `empresa_ids`: decir que cruzó dos
    // identidades sería inventárselo.
    fetchWithAuth.mockResolvedValue(BATALLAS);
    renderPestana([42, 43]);

    expect(await screen.findByText("Soporte SAP S/4HANA")).toBeInTheDocument();
    expect(screen.queryByText(/identidades del maestro/)).not.toBeInTheDocument();
  });

  it("con una sola identidad no manda grupo", async () => {
    fetchWithAuth.mockResolvedValue({ ...BATALLAS, claves: ["42"] });
    renderPestana([42]);

    expect(await screen.findByText("Soporte SAP S/4HANA")).toBeInTheDocument();
    expect(fetchWithAuth).toHaveBeenCalledWith(
      "/api/v1/competitive/empresas/42/contra-mi?meses=24&organization_id=21",
    );
    expect(screen.queryByText(/identidades del maestro/)).not.toBeInTheDocument();
  });

  it("sin cruces lo dice con la ventana, y cambiar la ventana vuelve a pedir", async () => {
    fetchWithAuth.mockResolvedValue({ ...BATALLAS, n: 0, batallas: [] });
    renderPestana();

    expect(await screen.findByText(/Ningún expediente en los últimos 24 meses/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "36 meses" }));
    await waitFor(() =>
      expect(fetchWithAuth).toHaveBeenLastCalledWith(
        "/api/v1/competitive/empresas/42/contra-mi?meses=36&organization_id=21",
      ),
    );
  });
});
