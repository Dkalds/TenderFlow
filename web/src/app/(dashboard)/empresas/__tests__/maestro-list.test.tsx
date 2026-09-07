/**
 * Buscador del maestro: orden por cabecera, paginación con recuento honesto.
 *
 * El listado enseñaba 14 filas y decía «14 de 1.284» sin forma de ver la 15, y
 * el inventario declaraba un orden por importe que ninguna cabecera ofrecía.
 * Estos tests fijan las dos cosas que lo arreglan.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MaestroList, ventanaDePaginas } from "../_components/maestro-list";
import type { EmpresaRow } from "../_hooks/use-maestro";

const ROWS: EmpresaRow[] = [
  {
    empresa_id: 1,
    nombre_canonico: "Indra Sistemas, S.A.",
    nif_canonico: "A28599033",
    es_ute: 0,
    es_pyme: 0,
    grupo: "Indra",
    n_adjudicaciones: 148,
    importe_total: 412_000_000,
  },
  {
    empresa_id: 2,
    nombre_canonico: "UTE Indra-Telefónica",
    nif_canonico: null,
    es_ute: 1,
    es_pyme: 0,
    grupo: null,
    n_adjudicaciones: 7,
    importe_total: 84_000_000,
  },
  {
    empresa_id: 3,
    nombre_canonico: "Seidor, S.A.",
    nif_canonico: "A58245757",
    es_ute: 0,
    es_pyme: 1,
    grupo: null,
    n_adjudicaciones: 64,
    importe_total: 161_000_000,
  },
];

function renderLista(overrides: Partial<React.ComponentProps<typeof MaestroList>> = {}) {
  const props: React.ComponentProps<typeof MaestroList> = {
    search: "",
    onSearchChange: vi.fn(),
    fromDeepLink: false,
    rows: ROWS,
    total: 1284,
    page: 0,
    onPageChange: vi.fn(),
    sortKey: "importe",
    sortDir: "desc",
    onSort: vi.fn(),
    selectedId: 1,
    onSelect: vi.fn(),
    watchedIds: new Set<number>([3]),
    onToggleWatch: vi.fn(),
    watchPending: false,
    loading: false,
    error: false,
    onRetry: vi.fn(),
    ...overrides,
  };
  return { props, ...render(<MaestroList {...props} />) };
}

afterEach(() => cleanup());

describe("ventanaDePaginas", () => {
  it("las pinta todas cuando caben", () => {
    expect(ventanaDePaginas(0, 4)).toEqual([0, 1, 2, 3]);
  });

  it("con 107 páginas enseña una ventana alrededor de la actual", () => {
    // 1.284 empresas de 12 en 12 son 107 páginas: pintarlas todas empuja el
    // contador fuera de la vista y nadie pulsa la 73.
    expect(ventanaDePaginas(50, 107)).toEqual([47, 48, 49, 50, 51, 52, 53]);
  });

  it("no se sale por ninguno de los dos extremos", () => {
    expect(ventanaDePaginas(0, 107)).toEqual([0, 1, 2, 3, 4, 5, 6]);
    expect(ventanaDePaginas(106, 107)).toEqual([100, 101, 102, 103, 104, 105, 106]);
  });
});

describe("MaestroList", () => {
  it("cuenta sobre el total del filtro, no sobre la página", () => {
    renderLista();
    expect(screen.getByText(/Mostrando 1–12 de 1.284/)).toBeInTheDocument();
  });

  it("cada cabecera de dato ordena", () => {
    const { props } = renderLista();
    fireEvent.click(screen.getByRole("button", { name: "Ordenar por NIF" }));
    expect(props.onSort).toHaveBeenCalledWith("nif");
    fireEvent.click(screen.getByRole("button", { name: "Ordenar por Importe" }));
    expect(props.onSort).toHaveBeenCalledWith("importe");
  });

  it("la columna de la estrella se llama «Vigilar», que es lo que hace", () => {
    // Se llamaba «Ver» y dentro tenía el botón de vigilar: la cabecera mentía.
    renderLista();
    expect(screen.getByText("Vigilar")).toBeInTheDocument();
  });

  it("la estrella dice si la empresa ya está vigilada y alterna sin abrir la ficha", () => {
    const { props } = renderLista();
    const botones = screen.getAllByRole("button", { name: /vigilar/i });
    fireEvent.click(botones[0]);
    // La primera fila no está vigilada: el clic pide seguirla.
    expect(props.onToggleWatch).toHaveBeenCalledWith(1, false);
    expect(props.onSelect).not.toHaveBeenCalled();
    // La tercera sí lo está, así que su botón ofrece dejar de vigilarla.
    expect(screen.getByRole("button", { name: "Dejar de vigilar" })).toHaveAttribute("aria-pressed", "true");
  });

  it("UTE y PYME son texto, no cápsulas de color", () => {
    renderLista();
    expect(screen.getByText("UTE")).toBeInTheDocument();
    expect(screen.getByText("PYME")).toBeInTheDocument();
  });

  it("marca la búsqueda que llega por deep-link y deja limpiarla", () => {
    const { props } = renderLista({ search: "Indra", fromDeepLink: true });
    expect(screen.getByText("desde grafo")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Limpiar búsqueda" }));
    expect(props.onSearchChange).toHaveBeenCalledWith("");
  });

  it("sin resultados propone el backfill en vez de dejar la tabla en blanco", () => {
    renderLista({ rows: [], total: 0 });
    expect(screen.getByText("Sin resultados")).toBeInTheDocument();
    expect(screen.getByText(/backfill del maestro/)).toBeInTheDocument();
  });

  it("el error del maestro es del bloque, con su código y su reintento", () => {
    const { props } = renderLista({ error: true, errorDetail: "500 · /api/v1/empresas" });
    expect(screen.getByRole("alert")).toHaveTextContent("No se pudo cargar el maestro");
    expect(screen.getByText("500 · /api/v1/empresas")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Reintentar/ }));
    expect(props.onRetry).toHaveBeenCalled();
    // Y no pinta la tabla debajo del error.
    expect(screen.queryByText("Indra Sistemas, S.A.")).not.toBeInTheDocument();
  });

  it("en la primera página no se puede retroceder", () => {
    renderLista();
    expect(screen.getByRole("button", { name: "Página anterior" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Página siguiente" })).toBeEnabled();
  });

  it("cargando enseña esqueletos y no la paginación", () => {
    renderLista({ loading: true });
    expect(screen.queryByText(/Mostrando/)).not.toBeInTheDocument();
    expect(screen.queryByText("Indra Sistemas, S.A.")).not.toBeInTheDocument();
  });
});
