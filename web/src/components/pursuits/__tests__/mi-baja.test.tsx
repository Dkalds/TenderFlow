/**
 * «Tu baja frente al mercado» en la pestaña Precio (C6.5).
 *
 * Lo que se fija: la petición lleva la organización activa, las cifras salen
 * tal como las da el backend (aquí no se recalcula nada), el órgano de la
 * ficha sube arriba, una muestra corta se marca, y sin ofertas el vacío lo
 * dice en vez de pintar una tabla de ceros.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/hooks/use-organization", () => ({
  useActiveOrganizationId: () => 7,
  organizacionResuelta: (id: unknown) => id !== undefined,
}));

import { MiBajaPanel, formatDelta, ordenarSegmentos } from "@/components/pursuits/mi-baja";
import type { MiBajaSegmento } from "@/hooks/use-mi-baja";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

function segmento(over: Partial<MiBajaSegmento>): MiBajaSegmento {
  return {
    segmento: "cpv4",
    clave: "7220",
    n: 6,
    baja_propia_pct: 12.5,
    baja_mercado_pct: 10.0,
    contratos_mercado: 40,
    suficiente: true,
    delta_pct: 2.5,
    ...over,
  };
}

function pintar(cuerpo: unknown, organo: string | null = null) {
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(cuerpo)));
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MiBajaPanel organo={organo} />
    </QueryClientProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MiBajaPanel", () => {
  it("pide la baja de la organización activa y pinta las cifras del backend", async () => {
    const fetchMock = pintar({
      organization_id: 7,
      base: "sin_iva",
      ofertas_consideradas: 6,
      segmentos: [segmento({})],
    });

    const fila = (await screen.findByText("CPV 7220")).closest("tr") as HTMLElement;
    expect(callUrl(fetchMock.mock.calls[0])).toBe("/api/v1/pursuits/mi-baja?organization_id=7");
    expect(within(fila).getByText("12,5%")).toBeInTheDocument();
    expect(within(fila).getByText("10,0%")).toBeInTheDocument();
    expect(within(fila).getByText("40 contratos")).toBeInTheDocument();
    expect(within(fila).getByText("+2,5 pp")).toBeInTheDocument();
    expect(screen.getByText(/Sin IVA · 6 ofertas presentadas/)).toBeInTheDocument();
  });

  it("sube y marca el órgano de la ficha, y marca la muestra corta", async () => {
    pintar(
      {
        organization_id: 7,
        base: "sin_iva",
        ofertas_consideradas: 8,
        segmentos: [
          segmento({}),
          segmento({ segmento: "organo", clave: "Ayuntamiento de Getafe", n: 2, suficiente: false, delta_pct: -1 }),
        ],
      },
      "  ayuntamiento de getafe ",
    );

    const filas = (await screen.findAllByRole("row")).slice(1);
    expect(within(filas[0]).getByText("Ayuntamiento de Getafe")).toBeInTheDocument();
    expect(within(filas[0]).getByText("Este órgano")).toBeInTheDocument();
    expect(within(filas[0]).getByText("Muestra corta")).toBeInTheDocument();
    expect(within(filas[0]).getByText("−1,0 pp")).toBeInTheDocument();
    expect(within(filas[1]).queryByText("Muestra corta")).toBeNull();
  });

  it("un segmento sin referencia de mercado lo dice, sin inventar diferencia", async () => {
    pintar({
      organization_id: 7,
      base: "sin_iva",
      ofertas_consideradas: 6,
      segmentos: [segmento({ baja_mercado_pct: null, contratos_mercado: 0, delta_pct: null })],
    });

    const fila = (await screen.findByText("CPV 7220")).closest("tr") as HTMLElement;
    expect(within(fila).getByText("Sin referencia")).toBeInTheDocument();
    expect(within(fila).getByText("—")).toBeInTheDocument();
  });

  it("sin ofertas presentadas el vacío explica qué cuenta", async () => {
    pintar({ organization_id: 7, base: "sin_iva", ofertas_consideradas: 0, segmentos: [] });

    expect(await screen.findByText("Todavía no hay ofertas tuyas con las que comparar")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("formatDelta y ordenarSegmentos", () => {
  it("el signo es el del backend: positiva es bajar más que el mercado", () => {
    expect(formatDelta(2.25)).toBe("+2,3 pp");
    expect(formatDelta(0)).toBe("0,0 pp");
    expect(formatDelta(null)).toBe("—");
  });

  it("sin órgano en la ficha conserva el orden del backend", () => {
    const lista = [segmento({ clave: "A" }), segmento({ clave: "B" })];
    expect(ordenarSegmentos(lista, null)).toBe(lista);
  });
});
