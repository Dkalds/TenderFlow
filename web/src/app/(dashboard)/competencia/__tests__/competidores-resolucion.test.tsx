/**
 * El aviso de cobertura del maestro, en la pantalla de las cuotas.
 *
 * Fija el umbral compartido con Empresas —el mismo número decide en las dos
 * pantallas— y que sin motivo no se pinta nada.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { fetchWithAuth } = vi.hoisted(() => ({ fetchWithAuth: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ fetchWithAuth }));

import { empresasKeys } from "@/lib/query-keys";
import { CompetidoresResolucion } from "../_components/competidores-resolucion";

function stats(pctImporte: number) {
  return {
    adjudicaciones_total: 5146,
    adjudicaciones_enlazadas: 4725,
    pct_filas: 93.4,
    importe_total: 1_000_000_000,
    importe_enlazado: pctImporte * 10_000_000,
    pct_importe: pctImporte,
    empresas: 1284,
    revisiones_pendientes: 8,
  };
}

function renderAviso(respuesta: Promise<unknown>) {
  fetchWithAuth.mockReturnValue(respuesta);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CompetidoresResolucion />
    </QueryClientProvider>,
  );
  return client;
}

/** Espera a que la consulta de cobertura termine, bien o mal. */
async function esperaCobertura(client: QueryClient, estado: "success" | "error") {
  await waitFor(() => expect(client.getQueryState(empresasKeys.stats)?.status).toBe(estado));
}

afterEach(() => {
  cleanup();
  fetchWithAuth.mockReset();
});

describe("CompetidoresResolucion", () => {
  it("por debajo del umbral avisa de las cuotas y lleva a la cola de revisión", async () => {
    renderAviso(Promise.resolve(stats(91.8)));

    const aviso = await screen.findByRole("note");
    expect(aviso).toHaveTextContent("Cuotas aproximadas");
    expect(aviso).toHaveTextContent("Solo el 91,8% del importe adjudicado");
    expect(aviso).toHaveTextContent("el umbral es el 95%");
    expect(screen.getByRole("link", { name: "Revisar en Empresas" })).toHaveAttribute(
      "href",
      "/empresas?vista=revision",
    );
    expect(fetchWithAuth).toHaveBeenCalledWith("/api/v1/empresas/stats");
  });

  it("en el umbral o por encima no dice nada", async () => {
    const client = renderAviso(Promise.resolve(stats(95)));

    await esperaCobertura(client, "success");
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("si la cobertura no llega, no inventa un aviso", async () => {
    const client = renderAviso(Promise.reject(new Error("503")));

    await esperaCobertura(client, "error");
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});
