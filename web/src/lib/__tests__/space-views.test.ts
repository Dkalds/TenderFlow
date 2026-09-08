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
  it("cubre los espacios multivista con su recuento", () => {
    // Los recuentos son el contrato de `docs/redesign/README.md`. Si uno cambia
    // sin actualizar el doc, la tabla del README miente. `ajustes` entró con
    // C7.5: cuatro vistas, de las que solo `cuenta` absorbe una ruta heredada
    // (`/mi-cuenta`) — las otras tres no existían en ninguna parte.
    expect(Object.keys(SPACE_VIEWS).sort()).toEqual([
      "ajustes",
      "competencia",
      "cuentas",
      "direccion",
      "empresas",
      "mercado",
      "mi-pipeline",
      "ops",
    ]);
    expect(SPACE_VIEWS.mercado).toHaveLength(8);
    expect(SPACE_VIEWS.competencia).toHaveLength(2);
    expect(SPACE_VIEWS["mi-pipeline"]).toHaveLength(4);
    expect(SPACE_VIEWS.ops).toHaveLength(6);
    expect(SPACE_VIEWS.empresas).toHaveLength(2);
    expect(SPACE_VIEWS.cuentas).toHaveLength(2);
    expect(SPACE_VIEWS.direccion).toHaveLength(3);
    expect(SPACE_VIEWS.ajustes).toHaveLength(4);
  });

  it("los espacios que no consolidan nada no declaran rutas heredadas", () => {
    // `empresas` tenía sus dos vistas dentro de `/empresas`; `cuentas` y
    // `direccion` son espacios nuevos del plan de funcionalidades 2026-09.
    // Los tres entran en la tabla para ser direccionables (`?vista=`), no para
    // absorber nada, y por eso el recuento de rutas heredadas de abajo no sube.
    for (const slug of ["empresas", "cuentas", "direccion"]) {
      expect(
        SPACE_VIEWS[slug].every((view) => view.from === undefined),
        `${slug} no debería absorber rutas`,
      ).toBe(true);
    }
  });

  it("absorbe cada ruta heredada una sola vez", () => {
    // El total se **deriva** de la tabla en vez de fijarse a mano: un número
    // literal aquí obliga a tocar el test en cada espacio nuevo y no dice nada
    // que la propia tabla no diga. Lo que sí hay que sostener es que dos
    // espacios no se peleen por la misma ruta heredada, porque el redirect que
    // ganara sería el del orden de declaración — invisible hasta producción.
    const origenes = allViews()
      .map(([, view]) => view.from)
      .filter(Boolean);
    expect(origenes.length).toBeGreaterThan(0);
    expect(new Set(origenes).size).toBe(origenes.length);
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
  it("declara los espacios sin repetir y sin barra inicial", () => {
    expect(new Set(BUILT_SPACE_ROUTES).size).toBe(BUILT_SPACE_ROUTES.length);
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
    // Derivado: uno por vista con `from` de un espacio ya construido.
    const esperados = allViews().filter(
      ([slug, view]) => view.from && BUILT_SPACE_ROUTES.includes(slug),
    ).length;
    expect(redirects).toHaveLength(esperados);
    expect(redirects).toContainEqual({
      source: "/tendencias",
      destination: "/mercado?vista=tiempo",
    });
    expect(redirects).toContainEqual({
      source: "/active-learning",
      destination: "/ops?vista=etiquetado",
    });
    // C7.5: `/mi-cuenta` sigue viva y lleva a su vista dentro de Ajustes.
    expect(redirects).toContainEqual({
      source: "/mi-cuenta",
      destination: "/ajustes?vista=cuenta",
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
