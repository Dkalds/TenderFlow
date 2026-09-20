/**
 * F1.1 — `busqueda_realizada` del listado: una vez por combinación de filtros
 * con respuesta, en tramos, y nunca sin filtros ni mientras carga.
 */
import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { registrarEvento } = vi.hoisted(() => ({ registrarEvento: vi.fn() }));
vi.mock("@/lib/analytics", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/analytics")>()),
  registrarEvento,
}));

import { useBusquedaListado } from "../_hooks/use-busqueda-listado";

afterEach(() => registrarEvento.mockReset());

describe("useBusquedaListado", () => {
  it("mide la búsqueda al llegar la respuesta, con el tramo de filtros y sin repetir", () => {
    const filtros = { provincia: "Sevilla", procedimiento: "1", importe_max: "5" };
    const { rerender } = renderHook(
      ({ cargando, total }) => useBusquedaListado(filtros, { total }, cargando),
      { initialProps: { cargando: true, total: 0 } },
    );
    expect(registrarEvento).not.toHaveBeenCalled();

    rerender({ cargando: false, total: 12 });
    expect(registrarEvento).toHaveBeenCalledWith("busqueda_realizada", {
      superficie: "listado",
      con_resultados: "si",
      filtros: "3+",
    });
    // Paginar o reordenar es la misma búsqueda.
    rerender({ cargando: false, total: 12 });
    expect(registrarEvento).toHaveBeenCalledTimes(1);
  });

  it("abrir la tabla sin filtros no es buscar", () => {
    renderHook(() => useBusquedaListado({}, { total: 900 }, false));
    expect(registrarEvento).not.toHaveBeenCalled();
  });
});
