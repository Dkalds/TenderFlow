/**
 * Pestaña «Identidad» del dossier: el maestro de cada identidad que suma.
 *
 * Fija lo que la ficha de `/empresas` enseñaba y el dossier debe conservar
 * (NIF, alias, relaciones de UTE), que una ficha agrupada dice cuántas
 * identidades suma, y que el fallo de una no se lleva a las demás.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { Schemas } from "@/lib/api-types";

const { fetchWithAuth } = vi.hoisted(() => ({ fetchWithAuth: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ fetchWithAuth }));

import { CompanyIdentidad } from "../company-identidad";

type Detalle = Schemas["EmpresaDetail"];

function detalle(parcial: Partial<Detalle> & Pick<Detalle, "empresa_id" | "nombre_canonico">): Detalle {
  return {
    nif_canonico: null,
    es_ute: 0,
    es_pyme: null,
    grupo: null,
    aliases: [],
    ute_miembros: [],
    participa_en_utes: [],
    created_at: null,
    updated_at: null,
    ...parcial,
  };
}

function alias(n: number, nifVariante: string | null = null): Detalle["aliases"] {
  return Array.from({ length: n }, (_, i) => ({
    alias_normalizado: `alias ${i}`,
    nif_variante: nifVariante,
    fuente: "placsp",
    confianza: null,
  }));
}

function renderIdentidad(empresaIds: number[], porId: Record<number, Detalle | Error>) {
  fetchWithAuth.mockImplementation((url: string) => {
    const respuesta = porId[Number(url.split("/").at(-1))];
    return respuesta instanceof Error ? Promise.reject(respuesta) : Promise.resolve(respuesta);
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CompanyIdentidad empresaIds={empresaIds} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  fetchWithAuth.mockReset();
});

describe("CompanyIdentidad", () => {
  it("enseña el maestro de la empresa: NIF, alias, UTE y el enlace al maestro", async () => {
    renderIdentidad([7], {
      7: detalle({
        empresa_id: 7,
        nombre_canonico: "Ejemplo Digital",
        nif_canonico: "NIF-7",
        grupo: "Ejemplo",
        aliases: [...alias(13, "NIF-7"), ...alias(1, "NIF-7B")],
        participa_en_utes: [{ empresa_id: 30, nombre_canonico: "UTE Ejemplo-Norte" }],
      }),
    });

    expect(await screen.findByRole("heading", { name: "Ejemplo Digital" })).toBeInTheDocument();
    expect(screen.getByText("NIF-7")).toBeInTheDocument();
    // El NIF de fuente distinto del canónico es lo que explica una agrupación.
    expect(screen.getByText("NIF-7B")).toBeInTheDocument();
    expect(screen.getByText("Grupo")).toBeInTheDocument();
    // Doce a la vista y el resto contado, no escondido sin decirlo.
    expect(screen.getByText("Alias vistos en fuente (14)")).toBeInTheDocument();
    expect(screen.getByText("+2 más")).toBeInTheDocument();
    // Cada UTE lleva a su propia ficha, en la ruta nueva.
    expect(screen.getByRole("link", { name: "UTE Ejemplo-Norte" })).toHaveAttribute("href", "/competencia/empresa/30");
    expect(screen.getByRole("link", { name: "Ver en el maestro" })).toHaveAttribute("href", "/empresas?q=NIF-7");
    // Una sola identidad no necesita explicar ninguna suma.
    expect(screen.queryByText(/identidades del maestro/)).not.toBeInTheDocument();
  });

  it("una ficha agrupada dice cuántas identidades suma y enseña cada una", async () => {
    renderIdentidad([7, 8], {
      7: detalle({ empresa_id: 7, nombre_canonico: "Ejemplo Digital" }),
      8: detalle({ empresa_id: 8, nombre_canonico: "Ejemplo Digital Sociedad Limitada" }),
    });

    expect(await screen.findByRole("heading", { name: "Ejemplo Digital Sociedad Limitada" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ejemplo Digital" })).toBeInTheDocument();
    expect(screen.getByText(/suma 2 identidades del maestro/)).toBeInTheDocument();
    // Sin NIF, el maestro se busca por nombre.
    expect(screen.getAllByRole("link", { name: "Ver en el maestro" })[0]).toHaveAttribute(
      "href",
      "/empresas?q=Ejemplo%20Digital",
    );
  });

  it("el fallo de una identidad es suyo: las demás se siguen viendo", async () => {
    renderIdentidad([7, 8], {
      7: detalle({ empresa_id: 7, nombre_canonico: "Ejemplo Digital" }),
      8: new Error("404"),
    });

    expect(await screen.findByRole("heading", { name: "Ejemplo Digital" })).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo cargar esta identidad");
    expect(screen.getByText("GET /api/v1/empresas/8")).toBeInTheDocument();
  });
});
