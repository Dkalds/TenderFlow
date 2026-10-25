import { describe, it, expect } from "vitest";
import {
  SECTIONS,
  ALL_PAGES,
  findPage,
  pageGlobalFilterKeys,
  pathUsesGlobalFilters,
} from "@/lib/navigation";

describe("SECTIONS (NAV_SECTIONS)", () => {
  it("is a non-empty array", () => {
    expect(Array.isArray(SECTIONS)).toBe(true);
    expect(SECTIONS.length).toBeGreaterThan(0);
  });

  it("every section has a label string", () => {
    for (const section of SECTIONS) {
      expect(typeof section.label).toBe("string");
      expect(section.label.length).toBeGreaterThan(0);
    }
  });

  it("every section has an items/pages array", () => {
    for (const section of SECTIONS) {
      expect(Array.isArray(section.pages)).toBe(true);
    }
  });
});

describe("findPage", () => {
  it("returns the resumen page for slug 'resumen'", () => {
    const page = findPage("resumen");
    expect(page).toBeDefined();
    expect(page?.slug).toBe("resumen");
    expect(page?.label).toBe("Resumen");
  });

  it("returns undefined for a nonexistent slug", () => {
    expect(findPage("nonexistent")).toBeUndefined();
    expect(findPage("/nonexistent")).toBeUndefined();
  });

  it("returns correct page for other known slugs", () => {
    const tendencias = findPage("tendencias");
    expect(tendencias?.slug).toBe("tendencias");

    const competidores = findPage("competidores");
    expect(competidores?.slug).toBe("competidores");
  });

  it("returned page has required fields: label, slug, description", () => {
    const page = findPage("resumen");
    expect(page).toMatchObject({
      label: expect.any(String),
      slug: expect.any(String),
      description: expect.any(String),
    });
  });
});

describe("descripciones del catálogo de páginas", () => {
  it("describe las páginas sin jerga de implementación", () => {
    const jerga = /(RAG|corpus|dataset|scraping|DLQ|heatmap|treemap|ARIMA|keywords?)/i;
    for (const page of ALL_PAGES) expect(page.description, page.slug).not.toMatch(jerga);
  });
});

describe("ALL_PAGES", () => {
  it("is a flat array of all pages with section field", () => {
    expect(Array.isArray(ALL_PAGES)).toBe(true);
    expect(ALL_PAGES.length).toBeGreaterThan(0);
    for (const page of ALL_PAGES) {
      expect(typeof page.section).toBe("string");
      expect(typeof page.slug).toBe("string");
    }
  });
});

/**
 * Contrato de filtros de los espacios de la consola. Un espacio no lo declara
 * a mano: lo hereda de las rutas que absorbe. Esto es lo que evita que Ops
 * pinte una barra de ámbito que no filtra nada.
 */
describe("contrato de filtros de los espacios", () => {
  it("Ops no consume el ámbito: ninguna de sus cinco rutas lo hacía", () => {
    expect(pathUsesGlobalFilters("/ops")).toBe(false);
  });

  it("Mercado sí lo consume: sus ocho cortes analíticos aplican el ámbito entero", () => {
    // La novena vista, Renovaciones (desde 2026-09-20), sólo declara
    // tecnología, pero la unión manda: basta con que un corte consuma todos
    // los filtros para que el espacio los ofrezca todos.
    expect(pathUsesGlobalFilters("/mercado")).toBe(true);
    expect(pageGlobalFilterKeys("/mercado")).toBeNull();
  });

  it("la Agenda (/mi-pipeline) aplica solo tecnología y CCAA, lo que declara su única vista", () => {
    // La agenda (heredera de /pipeline-alertas) declara tecnología + CCAA.
    // Hasta 2026-09-20 el espacio absorbía también /renovaciones (solo
    // tecnología) y la barra mostraba la unión; hoy /renovaciones es de
    // Mercado y el contrato de la Agenda es el de la agenda.
    // `filtersApply` en scope-bar es `usesGlobalFilters || subset.length > 0`,
    // así que la barra sigue apareciendo aunque la vista declare `false`.
    expect(pathUsesGlobalFilters("/mi-pipeline")).toBe(false);
    expect(pageGlobalFilterKeys("/mi-pipeline")).toEqual(["tecnologia", "ccaa"]);
  });

  it("Competencia hereda el contrato completo de competidores y UTEs", () => {
    expect(pathUsesGlobalFilters("/competencia")).toBe(true);
    expect(pageGlobalFilterKeys("/competencia")).toBeNull();
  });

  it("una ruta desconocida mantiene el comportamiento histórico", () => {
    expect(pathUsesGlobalFilters("/ruta-que-no-existe")).toBe(true);
  });
});

describe("contrato de filtros de una vista", () => {
  // El espacio declara la unión de sus vistas; con `?vista=`, manda la vista.
  // Sin esto, Empresas —que no aplica el ámbito y en `/empresas` no pintaba
  // barra— la habría heredado de Competidores al pasar a ser vista de
  // Competencia.
  it("Empresas y Revisión no consumen el ámbito aunque Competencia sí", () => {
    expect(pathUsesGlobalFilters("/competencia", "empresas")).toBe(false);
    // La cola no absorbe ruta: hereda el contrato del espacio que fue,
    // a través de `ESPACIOS_ABSORBIDOS`.
    expect(pathUsesGlobalFilters("/competencia", "revision")).toBe(false);
    expect(pathUsesGlobalFilters("/competencia", "competidores")).toBe(true);
    expect(pageGlobalFilterKeys("/competencia", "competidores")).toBeNull();
  });

  it("Mercado › Renovaciones ofrece solo lo que aplica: tecnología", () => {
    expect(pageGlobalFilterKeys("/mercado", "renovaciones")).toEqual(["tecnologia"]);
    expect(pageGlobalFilterKeys("/mercado", "tiempo")).toBeNull();
  });

  it("sin vista, o con una que no absorbe nada, sigue mandando la unión del espacio", () => {
    expect(pathUsesGlobalFilters("/competencia", null)).toBe(true);
    expect(pageGlobalFilterKeys("/mercado", "no-existe")).toBeNull();
    expect(pathUsesGlobalFilters("/oportunidades", "tablero")).toBe(pathUsesGlobalFilters("/oportunidades"));
  });
});
