import { describe, it, expect } from "vitest";
import { SECTIONS, ALL_PAGES, findPage, findSection } from "@/lib/navigation";

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
    expect(section?.label).toBe("Vista General");
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
