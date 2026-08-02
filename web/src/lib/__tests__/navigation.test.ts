import { describe, it, expect } from "vitest";
import {
  SECTIONS,
  ALL_PAGES,
  PRODUCT_SPACES,
  findPage,
  findProductSpace,
  findSection,
  pageGlobalFilterKeys,
  pathUsesGlobalFilters,
} from "@/lib/navigation";

describe("primary product spaces", () => {
  it("organizes the product around Radar, Oportunidades and Mercado", () => {
    expect(PRODUCT_SPACES.map((space) => space.label)).toEqual(["Radar", "Oportunidades", "Mercado"]);
    expect(findProductSpace("radar")?.label).toBe("Radar");
    expect(findProductSpace("oportunidades/p-1")?.label).toBe("Oportunidades");
    expect(findProductSpace("competidores")?.label).toBe("Mercado");
  });
});

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

  it("every section has an icon", () => {
    for (const section of SECTIONS) {
      expect(section.icon).toBeDefined();
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

  it("returned page has required fields: label, slug, description, icon", () => {
    const page = findPage("resumen");
    expect(page).toMatchObject({
      label: expect.any(String),
      slug: expect.any(String),
      description: expect.any(String),
    });
    expect(page?.icon).toBeDefined();
  });
});

describe("findSection", () => {
  it("returns the section containing 'resumen'", () => {
    const section = findSection("resumen");
    expect(section).toBeDefined();
    expect(section?.label).toBe("Inicio");
  });

  it("returns undefined for a nonexistent slug", () => {
    expect(findSection("nonexistent")).toBeUndefined();
    expect(findSection("/nonexistent")).toBeUndefined();
  });

  it("returns correct section for 'competidores'", () => {
    const section = findSection("competidores");
    expect(section?.label).toBe("Competencia");
  });

  it("returned section has label and pages", () => {
    const section = findSection("resumen");
    expect(typeof section?.label).toBe("string");
    expect(Array.isArray(section?.pages)).toBe(true);
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

  it("Mercado sí lo consume: sus ocho vistas son análisis del ámbito", () => {
    expect(pathUsesGlobalFilters("/mercado")).toBe(true);
  });

  it("Mi Pipeline lo consume porque al menos una de sus vistas lo hace", () => {
    // /renovaciones sólo aplica tecnología, pero /pipeline-alertas aplica todo.
    expect(pathUsesGlobalFilters("/mi-pipeline")).toBe(true);
    expect(pageGlobalFilterKeys("/mi-pipeline")).toBeNull();
  });

  it("Competencia hereda el contrato completo de competidores y UTEs", () => {
    expect(pathUsesGlobalFilters("/competencia")).toBe(true);
    expect(pageGlobalFilterKeys("/competencia")).toBeNull();
  });

  it("una ruta desconocida mantiene el comportamiento histórico", () => {
    expect(pathUsesGlobalFilters("/ruta-que-no-existe")).toBe(true);
  });
});
