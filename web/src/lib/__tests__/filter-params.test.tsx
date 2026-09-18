/**
 * `filterParamsFromSearch` es la lectura del ámbito que hace el servidor, y
 * tiene que coincidir con la que hace `useFilterParams` en el navegador vía
 * nuqs. Si divergen, el prefetch de `resumen/page.tsx` hidrata una clave que
 * ningún hook lee: el servidor paga la petición y el cliente la repite.
 *
 * Por eso el test no fija salidas a mano: pasa la misma URL por las dos vías
 * —el hook real, con el adaptador de pruebas de nuqs— y exige igualdad.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook } from "@testing-library/react";
import { withNuqsTestingAdapter } from "nuqs/adapters/testing";

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));

import { useFilterParams } from "@/lib/filters";
import { filterParamsFromSearch } from "@/lib/filter-params";

afterEach(() => cleanup());

function viaHook(search: string): Record<string, string> {
  const { result } = renderHook(() => useFilterParams(), {
    wrapper: withNuqsTestingAdapter({ searchParams: search }),
  });
  return result.current;
}

const URLS = [
  "",
  "?tecnologia=SAP",
  "?tecnologia=SAP,Oracle&ccaa=MD,CT",
  "?q=erp%20sanitario&estado=PUB,EV&solo_abiertas=true",
  "?fecha_desde=2026-01-01&fecha_hasta=2026-06-30&importe_min=50000",
  // `importe_min=0` es un filtro, no una ausencia.
  "?importe_min=0",
  // Lo que el hook ignora, también lo ignora el servidor.
  "?solo_abiertas=false&comparar=true&rango_b_desde=2025-01-01&vista=organos",
  // Valores vacíos: nuqs los lee como el default "".
  "?tecnologia=&ccaa=&q=",
];

describe("filterParamsFromSearch", () => {
  it.each(URLS)("coincide con useFilterParams para %j", (search) => {
    const esperado = viaHook(search);
    expect(filterParamsFromSearch(new URLSearchParams(search))).toEqual(esperado);
  });

  it("acepta los searchParams de una página de servidor, con el primer valor si se repite", () => {
    // Next entrega `string[]` cuando la clave se repite; nuqs lee el primero.
    expect(
      filterParamsFromSearch({ tecnologia: ["SAP", "Oracle"], ccaa: "MD", vista: undefined }),
    ).toEqual(viaHook("?tecnologia=SAP&tecnologia=Oracle&ccaa=MD"));
  });

  it("sin ámbito devuelve un objeto vacío, que es la clave del caso común", () => {
    expect(filterParamsFromSearch({})).toEqual({});
  });
});
