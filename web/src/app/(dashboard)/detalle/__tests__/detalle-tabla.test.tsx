/**
 * Los cuatro estados del cuerpo de la tabla de Detalle: cargando, error, vacía
 * (con o sin recorte por cierre) y filas (refrescando o no). Uno solo a la vez:
 * antes eran cinco booleanos sueltos que el padre tenía que mantener coherentes.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { MergedRow } from "../_hooks/detalle-table-model";

// La fila tiene su propio test: aquí solo importa cuántas se pintan y si van atenuadas.
vi.mock("../_components/detalle-fila", () => ({
  DetalleFila: ({ row, atenuada }: { row: MergedRow; atenuada: boolean }) => (
    <tr data-testid="fila" data-atenuada={String(atenuada)}>
      <td>{row.id_externo}</td>
    </tr>
  ),
}));

import { DetalleTabla, estadoDeTabla, type EstadoTabla } from "../_components/detalle-tabla";

const FILAS = [{ id_externo: "a" }, { id_externo: "b" }] as unknown as MergedRow[];

function pintar(estado: EstadoTabla, handlers: { onRetry?: () => void; onLimpiar?: () => void } = {}) {
  return render(
    <DetalleTabla
      rows={estado.tipo === "filas" ? FILAS : []}
      sorting={[]}
      allPageSelected={false}
      onToggleAllPage={() => {}}
      onToggleSort={() => {}}
      estado={estado}
      onRetry={handlers.onRetry ?? (() => {})}
      onLimpiar={handlers.onLimpiar ?? (() => {})}
      detailId={null}
      cursor={0}
      rowSelection={{}}
      ccaas={[]}
      tecnologias={[]}
      compact={false}
      rowHeight={64}
      onOpen={() => {}}
      onToggleSelect={() => {}}
      onToggleCcaa={() => {}}
      onToggleTecnologia={() => {}}
    />,
  );
}

afterEach(cleanup);

describe("estadoDeTabla", () => {
  const base = { isLoading: false, isFetching: false, error: null, hayFilas: true, conRecorte: false };

  it("la primera carga gana a todo lo demás", () => {
    expect(estadoDeTabla({ ...base, isLoading: true, error: new Error("x"), hayFilas: false })).toEqual({
      tipo: "cargando",
    });
  });

  it("un fallo no se confunde con «sin resultados»", () => {
    const error = new Error("caída");
    expect(estadoDeTabla({ ...base, error, hayFilas: false })).toEqual({ tipo: "error", error });
  });

  it("sin filas es vacía, y lleva si hay recorte", () => {
    expect(estadoDeTabla({ ...base, hayFilas: false, conRecorte: true })).toEqual({ tipo: "vacia", conRecorte: true });
  });

  it("con filas, refrescando sale de isFetching", () => {
    expect(estadoDeTabla({ ...base, isFetching: true })).toEqual({ tipo: "filas", refrescando: true });
    expect(estadoDeTabla(base)).toEqual({ tipo: "filas", refrescando: false });
  });
});

describe("DetalleTabla", () => {
  it("cargando: esqueleto, sin filas, sin alerta y sin vacío", () => {
    const { container } = pintar({ tipo: "cargando" });
    expect(container.querySelectorAll("tbody tr")).toHaveLength(12);
    expect(screen.queryByTestId("fila")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Sin resultados")).toBeNull();
  });

  it("error: alerta fuera de la tabla con reintento, y la cabecera sigue", () => {
    const onRetry = vi.fn();
    pintar({ tipo: "error", error: new Error("caída") }, { onRetry });
    const alerta = screen.getByRole("alert");
    expect(alerta.closest("table")).toBeNull();
    expect(screen.getByText("No se pudo cargar la tabla")).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Seleccionar todas las filas de la página" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(onRetry).toHaveBeenCalledOnce();
    expect(screen.queryByTestId("fila")).toBeNull();
  });

  it("vacía sin recorte: limpia solo el ámbito", () => {
    const onLimpiar = vi.fn();
    pintar({ tipo: "vacia", conRecorte: false }, { onLimpiar });
    expect(screen.getByText("Ninguna licitación encaja con el ámbito actual.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Limpiar ámbito" }));
    expect(onLimpiar).toHaveBeenCalledOnce();
  });

  it("vacía con recorte: lo dice y el botón limpia los dos", () => {
    pintar({ tipo: "vacia", conRecorte: true });
    expect(
      screen.getByText("Ninguna licitación encaja con el ámbito actual ni con el recorte por fecha de cierre."),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Limpiar ámbito y recorte" })).toBeTruthy();
  });

  it("filas: una por fila, atenuadas solo mientras refresca", () => {
    pintar({ tipo: "filas", refrescando: false });
    expect(screen.getAllByTestId("fila").map((fila) => fila.dataset.atenuada)).toEqual(["false", "false"]);
    cleanup();
    pintar({ tipo: "filas", refrescando: true });
    expect(screen.getAllByTestId("fila").map((fila) => fila.dataset.atenuada)).toEqual(["true", "true"]);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Sin resultados")).toBeNull();
  });
});
