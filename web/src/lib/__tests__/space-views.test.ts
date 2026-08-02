import { describe, it, expect } from "vitest";
import {
  BUILT_SPACE_ROUTES,
  SPACE_VIEWS,
  legacyRedirects,
  type SpaceView,
} from "@/lib/space-views";

const allViews = (): [string, SpaceView][] =>
  Object.entries(SPACE_VIEWS).flatMap(([slug, views]) =>
    views.map((view) => [slug, view] as [string, SpaceView]),
  );

describe("SPACE_VIEWS", () => {
  it("cubre los cinco espacios multivista con su recuento del rediseño", () => {
    // Los recuentos son el contrato de `docs/redesign/README.md`: 19 rutas
    // heredadas repartidas en cinco espacios. Si uno cambia sin actualizar el
    // doc, la tabla del README miente.
    expect(Object.keys(SPACE_VIEWS).sort()).toEqual([
      "competencia",
      "mercado",
      "mi-pipeline",
      "ops",
      "relaciones",
    ]);
    expect(SPACE_VIEWS.mercado).toHaveLength(8);
    expect(SPACE_VIEWS.competencia).toHaveLength(2);
    expect(SPACE_VIEWS.relaciones).toHaveLength(2);
    expect(SPACE_VIEWS["mi-pipeline"]).toHaveLength(2);
    expect(SPACE_VIEWS.ops).toHaveLength(5);
  });

  it("absorbe 19 rutas heredadas, todas distintas", () => {
    const origenes = allViews()
      .map(([, view]) => view.from)
      .filter(Boolean);
    expect(origenes).toHaveLength(19);
    expect(new Set(origenes).size).toBe(19);
  });

  it("da a cada vista una clave única dentro de su espacio y una etiqueta", () => {
    for (const [slug, views] of Object.entries(SPACE_VIEWS)) {
      const keys = views.map((view) => view.key);
      expect(new Set(keys).size, `claves repetidas en ${slug}`).toBe(keys.length);
      for (const view of views) {
        expect(view.key).toMatch(/^[a-z0-9-]+$/);
        expect(view.label.length).toBeGreaterThan(0);
      }
    }
  });
});

describe("BUILT_SPACE_ROUTES", () => {
  it("declara los 14 espacios, sin repetir y sin barra inicial", () => {
    expect(BUILT_SPACE_ROUTES).toHaveLength(14);
    expect(new Set(BUILT_SPACE_ROUTES).size).toBe(14);
    for (const slug of BUILT_SPACE_ROUTES) {
      expect(slug.startsWith("/")).toBe(false);
    }
  });

  it("incluye todo espacio que tenga vistas: si no, sus rutas quedarían sin redirect", () => {
    for (const slug of Object.keys(SPACE_VIEWS)) {
      expect(BUILT_SPACE_ROUTES).toContain(slug);
    }
  });
});

describe("legacyRedirects", () => {
  it("emite un redirect por ruta absorbida hacia su `?vista=`", () => {
    const redirects = legacyRedirects();
    expect(redirects).toHaveLength(19);
    expect(redirects).toContainEqual({
      source: "/tendencias",
      destination: "/mercado?vista=tiempo",
    });
    expect(redirects).toContainEqual({
      source: "/active-learning",
      destination: "/ops?vista=etiquetado",
    });
  });

  it("no redirige una ruta sobre sí misma", () => {
    for (const { source, destination } of legacyRedirects()) {
      expect(destination.split("?")[0]).not.toBe(source);
    }
  });

  it("sale de cada origen a un único destino", () => {
    const sources = legacyRedirects().map((redirect) => redirect.source);
    expect(new Set(sources).size).toBe(sources.length);
  });

  it("sólo redirige espacios construidos", () => {
    // El filtro por `BUILT_SPACE_ROUTES` es lo que evita mandar una pantalla
    // viva a un 404 mientras su espacio no exista.
    for (const { destination } of legacyRedirects()) {
      const slug = destination.replace(/^\//, "").split("?")[0];
      expect(BUILT_SPACE_ROUTES).toContain(slug);
    }
  });
});
