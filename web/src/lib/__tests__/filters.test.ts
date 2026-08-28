/**
 * Tests for web/src/lib/filters.ts
 *
 * Covers: filtersToParams (pure function) y el viaje de ida y vuelta del ámbito
 * por la URL (al final del fichero).
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, act, cleanup, waitFor } from "@testing-library/react";
import { withNuqsTestingAdapter } from "nuqs/adapters/testing";
import {
  EMPTY_SCOPE,
  filtersToParams,
  appendFiltersToPath,
  mergeFiltersIntoPath,
  scopeKey,
  useFilters,
  useScopeSnapshot,
} from "@/lib/filters";
import type { FilterValues, FiltersState, ScopeSnapshot } from "@/lib/filters";

afterEach(() => {
  cleanup();
});

const emptyFilters: FilterValues = {
  q: "",
  rango: { desde: null, hasta: null },
  estados: [],
  ccaas: [],
  tecnologias: [],
  importeMin: null,
  soloAbiertas: false,
};

function makeFilters(overrides: Partial<FilterValues> = {}): FilterValues {
  return { ...emptyFilters, ...overrides };
}

describe("filtersToParams", () => {
  it("returns an empty object for empty filters", () => {
    expect(filtersToParams(emptyFilters)).toEqual({});
  });

  it("adds 'q' when q is non-empty", () => {
    const result = filtersToParams(makeFilters({ q: "software" }));
    expect(result).toEqual({ q: "software" });
  });

  it("does NOT add 'q' when q is empty string", () => {
    const result = filtersToParams(makeFilters({ q: "" }));
    expect(result.q).toBeUndefined();
  });

  it("adds fecha_desde from rango.desde", () => {
    const result = filtersToParams(makeFilters({ rango: { desde: "2024-01-01", hasta: null } }));
    expect(result.fecha_desde).toBe("2024-01-01");
    expect(result.fecha_hasta).toBeUndefined();
  });

  it("adds fecha_hasta from rango.hasta", () => {
    const result = filtersToParams(makeFilters({ rango: { desde: null, hasta: "2024-12-31" } }));
    expect(result.fecha_hasta).toBe("2024-12-31");
    expect(result.fecha_desde).toBeUndefined();
  });

  it("adds both fecha_desde and fecha_hasta when both are set", () => {
    const result = filtersToParams(makeFilters({ rango: { desde: "2024-01-01", hasta: "2024-06-30" } }));
    expect(result.fecha_desde).toBe("2024-01-01");
    expect(result.fecha_hasta).toBe("2024-06-30");
  });

  it("joins estados as comma-separated string under 'estado' key", () => {
    const result = filtersToParams(makeFilters({ estados: ["ADJ", "PUB"] }));
    expect(result.estado).toBe("ADJ,PUB");
  });

  it("omits estado when estados array is empty", () => {
    const result = filtersToParams(makeFilters({ estados: [] }));
    expect(result.estado).toBeUndefined();
  });

  it("handles a single estado value", () => {
    const result = filtersToParams(makeFilters({ estados: ["ADJ"] }));
    expect(result.estado).toBe("ADJ");
  });

  it("joins ccaas as comma-separated string under 'ccaa' key", () => {
    const result = filtersToParams(makeFilters({ ccaas: ["MD", "CT"] }));
    expect(result.ccaa).toBe("MD,CT");
  });

  it("omits ccaa when ccaas array is empty", () => {
    const result = filtersToParams(makeFilters({ ccaas: [] }));
    expect(result.ccaa).toBeUndefined();
  });

  it("joins tecnologias as comma-separated string under 'tecnologia' key", () => {
    const result = filtersToParams(makeFilters({ tecnologias: ["IA", "Cloud", "Ciberseguridad"] }));
    expect(result.tecnologia).toBe("IA,Cloud,Ciberseguridad");
  });

  it("omits tecnologia when tecnologias array is empty", () => {
    const result = filtersToParams(makeFilters({ tecnologias: [] }));
    expect(result.tecnologia).toBeUndefined();
  });

  it("adds importe_min as string when importeMin is set", () => {
    const result = filtersToParams(makeFilters({ importeMin: 50_000 }));
    expect(result.importe_min).toBe("50000");
  });

  it("adds importe_min even when it is 0", () => {
    const result = filtersToParams(makeFilters({ importeMin: 0 }));
    expect(result.importe_min).toBe("0");
  });

  it("omits importe_min when importeMin is null", () => {
    const result = filtersToParams(makeFilters({ importeMin: null }));
    expect(result.importe_min).toBeUndefined();
  });

  it("combines multiple filters correctly", () => {
    const result = filtersToParams(
      makeFilters({
        q: "SAP",
        rango: { desde: "2024-01-01", hasta: "2024-12-31" },
        estados: ["PUB"],
        ccaas: ["MD"],
        tecnologias: ["ERP"],
        importeMin: 10_000,
      }),
    );
    expect(result).toEqual({
      q: "SAP",
      fecha_desde: "2024-01-01",
      fecha_hasta: "2024-12-31",
      estado: "PUB",
      ccaa: "MD",
      tecnologia: "ERP",
      importe_min: "10000",
    });
  });
});

describe("appendFiltersToPath", () => {
  it("appends the filter query string to a plain path", () => {
    expect(appendFiltersToPath("/detalle", "?estado=PUB")).toBe("/detalle?estado=PUB");
  });

  it("returns the path untouched when there are no active filters", () => {
    expect(appendFiltersToPath("/detalle", "")).toBe("/detalle");
  });

  it("does NOT append when the path already carries its own query string", () => {
    // Deep-links that set a specific filtered view must keep overriding.
    expect(appendFiltersToPath("/detalle?lic=ABC123", "?estado=PUB")).toBe("/detalle?lic=ABC123");
  });

  it("leaves deep-links untouched even with no active filters", () => {
    expect(appendFiltersToPath("/detalle?lic=ABC123", "")).toBe("/detalle?lic=ABC123");
  });
});

describe("mergeFiltersIntoPath", () => {
  it("fusiona el ámbito con la query propia del enlace", () => {
    expect(mergeFiltersIntoPath("/detalle?solo_abiertas=true", "?ccaa=MD")).toBe(
      "/detalle?ccaa=MD&solo_abiertas=true",
    );
  });

  it("deja ganar al parámetro del enlace cuando la clave colisiona", () => {
    // La tarjeta «Nuevas 24h» fija su propia fecha: ésa es su razón de existir,
    // no la del chip de fecha del ámbito.
    expect(mergeFiltersIntoPath("/detalle?fecha_desde=2026-08-25", "?fecha_desde=2026-01-01")).toBe(
      "/detalle?fecha_desde=2026-08-25",
    );
  });

  it("se comporta como appendFiltersToPath cuando el path va limpio", () => {
    expect(mergeFiltersIntoPath("/detalle", "?estado=PUB")).toBe("/detalle?estado=PUB");
  });

  it("devuelve el path intacto sin ámbito activo", () => {
    expect(mergeFiltersIntoPath("/detalle?solo_abiertas=true", "")).toBe("/detalle?solo_abiertas=true");
  });
});

describe("filtersToParams · solo_abiertas", () => {
  /**
   * Este parámetro existe porque `estado=PUB,EV` no es equivalente a "abiertas".
   * La tarjeta "Total activas" de /resumen enlazaba a `?estado=PUB,EV` mientras
   * su contador pasaba a contar todo lo no terminal: decía 12 y su listado 0.
   */
  it("emite solo_abiertas cuando está activo", () => {
    expect(filtersToParams(makeFilters({ soloAbiertas: true })).solo_abiertas).toBe("true");
  });

  it("lo omite cuando no lo está, en vez de mandar 'false'", () => {
    expect(filtersToParams(makeFilters({ soloAbiertas: false })).solo_abiertas).toBeUndefined();
  });

  it("no enumera estados: convive con un filtro de estado sin pisarlo", () => {
    const result = filtersToParams(makeFilters({ soloAbiertas: true, estados: ["ADM"] }));
    expect(result).toEqual({ solo_abiertas: "true", estado: "ADM" });
  });
});

/* ── Ida y vuelta del ámbito por la URL ─────────────────────────────────
 *
 * Estos bloques van al final a propósito: escribir con los setters encola
 * escrituras en la cola global de nuqs, y se drenan aquí en vez de dejar que
 * contaminen los tests de función pura de arriba (mismo motivo que en
 * `filters-hooks.test.tsx`).
 *
 * Lo que fijan no es que los setters "no lancen" —eso ya estaba— sino que el
 * ámbito **vuelva entero** después de pasar por la URL. Es la mitad de cliente
 * del fallo de #220: el ámbito viaja como query string y cualquier eslabón que
 * lo pierda (una serialización que se come una clave, una navegación que se
 * queda con el pathname) deja al usuario mirando otros datos sin saberlo.
 */

/** Aplica acciones sobre `useFilters` y devuelve la query string resultante. */
async function urlTras(acciones: (filtros: FiltersState) => void): Promise<string> {
  const onUrlUpdate = vi.fn();
  const { result, unmount } = renderHook(() => useFilters(), {
    wrapper: withNuqsTestingAdapter({ onUrlUpdate }),
  });
  await act(async () => {
    acciones(result.current);
  });
  await waitFor(() => expect(onUrlUpdate).toHaveBeenCalled());
  const ultima = onUrlUpdate.mock.calls.at(-1)?.[0] as { queryString: string };
  unmount();
  return ultima.queryString;
}

/** Lee el ámbito que una query string representa. */
function leerFiltros(search: string): FiltersState {
  const { result } = renderHook(() => useFilters(), {
    wrapper: withNuqsTestingAdapter({ searchParams: search }),
  });
  return result.current;
}

const AMBITO_COMPLETO = (filtros: FiltersState): void => {
  // Acentos, espacios y `&` en la búsqueda: los tres caracteres que un
  // serializador descuidado rompe o trunca.
  filtros.setQ("obras hidráulicas & señalización");
  filtros.setEstados(["PUB", "ADJ"]);
  filtros.setCcaas(["Madrid", "Castilla-La Mancha"]);
  filtros.setTecnologias(["IA", "Cloud"]);
  filtros.setImporteMin(150_000);
  filtros.setSoloAbiertas(true);
  filtros.setComparar(true);
  filtros.setRango({ desde: "2026-01-01", hasta: "2026-06-30" });
  filtros.setRangoB({ desde: "2025-01-01", hasta: "2025-06-30" });
};

describe("useFilters · ida y vuelta por la URL", () => {
  it("los once parámetros del ámbito vuelven idénticos", async () => {
    const qs = await urlTras(AMBITO_COMPLETO);
    const vuelta = leerFiltros(qs);

    expect(vuelta.q).toBe("obras hidráulicas & señalización");
    expect(vuelta.estados).toEqual(["PUB", "ADJ"]);
    expect(vuelta.ccaas).toEqual(["Madrid", "Castilla-La Mancha"]);
    expect(vuelta.tecnologias).toEqual(["IA", "Cloud"]);
    expect(vuelta.importeMin).toBe(150_000);
    expect(vuelta.soloAbiertas).toBe(true);
    expect(vuelta.comparar).toBe(true);
    expect(vuelta.rango).toEqual({ desde: "2026-01-01", hasta: "2026-06-30" });
    expect(vuelta.rangoB).toEqual({ desde: "2025-01-01", hasta: "2025-06-30" });
  });

  it("un importe mínimo de 0 sobrevive y no se lee como «sin importe»", async () => {
    // `0` es falsy: el camino donde más fácil se pierde un filtro real.
    const qs = await urlTras((f) => f.setImporteMin(0));
    expect(leerFiltros(qs).importeMin).toBe(0);
  });

  it("un booleano apagado no viaja como «false», que se leería como encendido", async () => {
    const qs = await urlTras((f) => {
      f.setSoloAbiertas(true);
      f.setSoloAbiertas(false);
    });
    expect(new URLSearchParams(qs).get("solo_abiertas")).toBeNull();
    expect(leerFiltros(qs).soloAbiertas).toBe(false);
  });

  it("resetFilters deja la URL sin ninguna clave del ámbito", async () => {
    const qs = await urlTras((f) => {
      AMBITO_COMPLETO(f);
      f.resetFilters();
    });

    const params = new URLSearchParams(qs);
    for (const clave of Object.keys(EMPTY_SCOPE)) {
      expect(params.get(clave) ?? "").toBe("");
    }
    const vuelta = leerFiltros(qs);
    expect(vuelta.q).toBe("");
    expect(vuelta.estados).toEqual([]);
    expect(vuelta.ccaas).toEqual([]);
    expect(vuelta.importeMin).toBeNull();
    expect(vuelta.soloAbiertas).toBe(false);
    expect(vuelta.rango).toEqual({ desde: null, hasta: null });
  });

  it("el ámbito sobrevive a un enlace que ya trae su propia query", async () => {
    // El caso de #220: `/mercado` monta la vista de tendencias con `?vista=` y
    // el chip de tecnología tenía que llegar junto a ella, no en su lugar ni
    // pegado detrás de un segundo `?`.
    const qs = await urlTras((f) => f.setTecnologias(["SAP"]));
    const href = mergeFiltersIntoPath("/mercado?vista=tiempo", qs);

    expect(href.startsWith("/mercado?")).toBe(true);
    expect(href.split("?").length).toBe(2);
    const destino = new URLSearchParams(href.split("?")[1]);
    expect(destino.get("vista")).toBe("tiempo");
    expect(leerFiltros(href.split("?")[1]).tecnologias).toEqual(["SAP"]);
  });
});

describe("useScopeSnapshot", () => {
  it("lee los once parámetros crudos, incluidos los que useFilters deriva", () => {
    const { result } = renderHook(() => useScopeSnapshot(), {
      wrapper: withNuqsTestingAdapter({
        searchParams: "?q=obras&estado=PUB,ADJ&solo_abiertas=true",
      }),
    });
    expect(result.current.snapshot).toEqual({
      ...EMPTY_SCOPE,
      q: "obras",
      estado: "PUB,ADJ",
      solo_abiertas: "true",
    });
  });

  it("restaurar una instantánea es UNA sola actualización de URL", async () => {
    // Es la razón de existir del hook: con los setters sueltos, deshacer
    // generaba once entradas de historial y once refetch en cascada.
    const onUrlUpdate = vi.fn();
    const { result } = renderHook(() => useScopeSnapshot(), {
      wrapper: withNuqsTestingAdapter({ onUrlUpdate }),
    });
    const destino: ScopeSnapshot = {
      ...EMPTY_SCOPE,
      q: "grúas",
      ccaa: "Galicia",
      importe_min: "80000",
    };

    await act(async () => {
      result.current.applySnapshot(destino);
    });
    await waitFor(() => expect(onUrlUpdate).toHaveBeenCalled());

    expect(onUrlUpdate).toHaveBeenCalledTimes(1);
    const { queryString } = onUrlUpdate.mock.calls[0][0] as { queryString: string };
    const params = new URLSearchParams(queryString);
    expect(params.get("q")).toBe("grúas");
    expect(params.get("ccaa")).toBe("Galicia");
    expect(params.get("importe_min")).toBe("80000");
  });

  it("scopeKey distingue dos ámbitos que sólo difieren en una clave", () => {
    // El historial compara por esta cadena: si colisionaran, deshacer se
    // saltaría un paso en silencio.
    const base = { ...EMPTY_SCOPE, q: "obras" };
    expect(scopeKey(base)).toBe(scopeKey({ ...base }));
    expect(scopeKey(base)).not.toBe(scopeKey({ ...base, ccaa: "Madrid" }));
  });
});
