import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => 7,
  organizacionResuelta: () => true,
}));

import { FichaHistorialPropio } from "@/components/ficha/ficha-historial-propio";

function servir(respuesta: unknown) {
  const fetchMock = vi.fn(() => Promise.resolve(jsonResponse(respuesta)));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function montar() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FichaHistorialPropio licitacionId="EXP-1" />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("FichaHistorialPropio", () => {
  it("sin NIF declarado manda a declararlo en vez de enseñar ceros", async () => {
    const fetchMock = servir({ licitacion_id: "EXP-1", identidad_conocida: false, recientes: [] });
    montar();

    expect(await screen.findByText("Declara el NIF de tu organización")).toBeInTheDocument();
    expect(callUrl(fetchMock.mock.calls[0])).toBe("/api/v1/licitaciones/EXP-1/historial-propio?organization_id=7");
  });

  it("enseña lo ganado con el órgano y en el CPV, y las últimas adjudicaciones", async () => {
    servir({
      licitacion_id: "EXP-1",
      identidad_conocida: true,
      organo: "Ayuntamiento de Sevilla",
      cpv4: "7226",
      con_organo: { expedientes: 2, importe: 240000, baja_mediana_pct: 12.5, bajas_n: 2 },
      en_cpv4: { expedientes: 0, importe: 0, baja_mediana_pct: null, bajas_n: 0 },
      oportunidades: { total: 5, presentadas: 4, ganadas: 2, perdidas: 2 },
      recientes: [
        {
          licitacion_id: "EXP-VIEJO",
          titulo: "Soporte SAP 2024",
          organo_contratacion: "Ayuntamiento de Sevilla",
          fecha_adjudicacion: "2024-05-10",
          importe_adjudicado: 120000,
          baja_pct: 10,
          mismo_organo: true,
          mismo_cpv4: true,
        },
      ],
    });
    montar();

    expect(await screen.findByText(/^2 ganadas/)).toBeInTheDocument();
    expect(screen.getByText("Ninguna adjudicación")).toBeInTheDocument();
    expect(screen.getByText(/5 en total · 4 presentadas · 2 ganadas · 2 perdidas/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Soporte SAP 2024" })).toHaveAttribute("href", "/detalle?lic=EXP-VIEJO");
  });
});
