/**
 * El comparador de Detalle rellena con la ficha de cada expediente los campos
 * que el listado no trae (fuente, tipo de contrato, provincia, fechas de
 * ejecución y descripción), en vez de enseñarlos vacíos.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";
import { DetalleComparador } from "../_components/detalle-comparador";
import { row } from "./detalle-fixtures";

function ficha(id: string, extra: Record<string, unknown>) {
  return {
    id_externo: id,
    titulo: `Expediente ${id}`,
    organo_contratacion: "Ayuntamiento de Getafe",
    importe: 100000,
    estado: "PUB",
    fecha_publicacion: "2026-09-01",
    fecha_limite: "2026-10-30T12:00:00+00:00",
    ccaa: "Madrid",
    cpv: "72000000",
    url: null,
    tecnologia: "SAP",
    fuente: "placsp",
    tipo_contrato: "2",
    provincia: "Madrid",
    fecha_inicio: "2027-01-01",
    fecha_fin: "2028-12-31",
    descripcion: "Soporte y evolución de la plataforma SAP.",
    lotes: [],
    adjudicatarios: [],
    ...extra,
  };
}

function servir({ fallaB = false } = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn((...call: unknown[]) => {
      const url = callUrl(call);
      if (url.startsWith("/api/v1/meta/filters")) {
        return Promise.resolve(
          jsonResponse({ tipo_contrato: [{ codigo: "2", etiqueta: "Servicios", descripcion: null }] }),
        );
      }
      if (url === "/api/v1/licitaciones/EXP-A") return Promise.resolve(jsonResponse(ficha("EXP-A", {})));
      if (url === "/api/v1/licitaciones/EXP-B") {
        return Promise.resolve(
          fallaB
            ? jsonResponse({ detail: "Error interno" }, 500)
            : jsonResponse(ficha("EXP-B", { fuente: "ted", provincia: "Toledo" })),
        );
      }
      return Promise.reject(new Error(`petición inesperada: ${url}`));
    }),
  );
}

function montar() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DetalleComparador
        filas={[
          row({ id_externo: "EXP-A", titulo: "Expediente EXP-A", fecha_limite: "2026-10-30T12:00:00+00:00" }),
          row({ id_externo: "EXP-B", titulo: "Expediente EXP-B" }),
        ]}
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
}

function fila(rotulo: string): HTMLElement {
  return screen.getByRole("rowheader", { name: rotulo }).closest("tr") as HTMLElement;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("DetalleComparador", () => {
  it("compara también lo que solo trae la ficha", async () => {
    servir();
    montar();

    expect(await within(await screen.findByRole("dialog")).findByText("Toledo")).toBeInTheDocument();
    expect(within(fila("Fuente")).getByText("PLACSP")).toBeInTheDocument();
    expect(within(fila("Fuente")).getByText("TED")).toBeInTheDocument();
    expect(within(fila("Tipo de contrato")).getAllByText("Servicios")).toHaveLength(2);
    expect(within(fila("Provincia")).getByText("Madrid")).toBeInTheDocument();
    expect(within(fila("Descripción")).getAllByText("Soporte y evolución de la plataforma SAP.")).toHaveLength(2);
    expect(within(fila("Inicio de ejecución")).getAllByText(/2027/)).toHaveLength(2);
    expect(within(fila("Fin de ejecución")).getAllByText(/2028/)).toHaveLength(2);
    expect(screen.queryByText(/Cargando la ficha/)).not.toBeInTheDocument();
  });

  it("si una ficha falla lo dice, y esa columna se queda con lo del listado", async () => {
    servir({ fallaB: true });
    montar();

    expect(
      await screen.findByText("No se pudo cargar la ficha de EXP-B: sus campos de ficha salen vacíos."),
    ).toBeInTheDocument();
    expect(within(fila("Fuente")).getByText("PLACSP")).toBeInTheDocument();
  });
});
