import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { FichaSimilares } from "@/components/ficha/ficha-similares";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

function servir(respuesta: unknown) {
  const fetchMock = vi.fn(() => Promise.resolve(jsonResponse(respuesta)));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function montar(id = "PA-S 2026/000058") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FichaSimilares licitacionId={id} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("FichaSimilares", () => {
  it("lista los parecidos con su enlace y dice sobre cuántos y cómo se ordenaron", async () => {
    const fetchMock = servir({
      licitacion_id: "PA-S 2026/000058",
      predecesor: null,
      similares: [
        {
          id_externo: "EXP-OTRO",
          titulo: "Mantenimiento SAP S/4HANA",
          organo_contratacion: "Diputación de Cádiz",
          cpv: "72267100",
          importe: 120000,
          estado: "PUB",
          fecha_publicacion: "2026-08-01",
          score: 0.6,
        },
      ],
      metodo: "fts",
      n: 14,
    });
    montar();

    const enlace = await screen.findByRole("link", { name: /Mantenimiento SAP S\/4HANA/ });
    expect(enlace).toHaveAttribute("href", "/detalle?lic=EXP-OTRO");
    expect(screen.getByText(/Diputación de Cádiz/)).toBeInTheDocument();
    expect(screen.getByText(/14 expedientes del mismo CPV evaluados, ordenados por palabras en común/)).toBeInTheDocument();
    // El id lleva barra y espacio: viaja codificado.
    expect(callUrl(fetchMock.mock.calls[0])).toBe(
      "/api/v1/licitaciones/PA-S%202026%2F000058/similares?limit=5",
    );
  });

  it("sin candidatos dice que no había con qué comparar", async () => {
    servir({ licitacion_id: "X", predecesor: null, similares: [], metodo: "fts", n: 0 });
    montar("X");
    await waitFor(() =>
      expect(screen.getByText("No hay otros expedientes del mismo CPV con los que comparar.")).toBeInTheDocument(),
    );
  });
});
