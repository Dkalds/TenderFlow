import { describe, it, expect } from "vitest";
import {
  ADMIN_ONLY_SPACES,
  CONSOLE_GROUP_ORDER,
  CONSOLE_ROUTES,
  CONSOLE_SPACES,
  LEGACY_REDIRECTS,
  findConsoleSpace,
  isSpaceImplemented,
  landingHref,
  routeSlug,
  spaceAbsorbing,
} from "@/lib/console-spaces";
import { BUILT_SPACE_ROUTES, SPACE_VIEWS } from "@/lib/space-views";

describe("CONSOLE_SPACES", () => {
  it("consolida las 25 rutas del dashboard en 13 espacios", () => {
    expect(CONSOLE_SPACES).toHaveLength(13);
    const absorbed = CONSOLE_SPACES.flatMap((space) => space.views ?? []).filter(
      (view) => view.from,
    );
    expect(absorbed).toHaveLength(17);
  });

  it("da a cada espacio clave y slug únicos, y una etiqueta corta de 2-3 letras", () => {
    const keys = CONSOLE_SPACES.map((space) => space.key);
    const slugs = CONSOLE_SPACES.map((space) => space.slug);
    expect(new Set(keys).size).toBe(keys.length);
    expect(new Set(slugs).size).toBe(slugs.length);
    for (const space of CONSOLE_SPACES) {
      expect(space.short).toMatch(/^[A-Z]{2,3}$/);
      expect(space.label.length).toBeGreaterThan(0);
      expect(space.description.length).toBeGreaterThan(0);
      expect(space.icon).toBeDefined();
    }
  });

  it("asigna cada espacio a un grupo del rail", () => {
    for (const space of CONSOLE_SPACES) {
      expect(CONSOLE_GROUP_ORDER).toContain(space.group);
    }
    // Ningún grupo del rail puede quedar vacío: pintaría un separador suelto.
    for (const group of CONSOLE_GROUP_ORDER) {
      expect(CONSOLE_SPACES.some((space) => space.group === group)).toBe(true);
    }
  });

  it("toma sus vistas de la tabla compartida con next.config.ts", () => {
    // Si `console-spaces` copiase las vistas en vez de importarlas, los
    // redirects del build y el rail podrían divergir en silencio.
    for (const [slug, views] of Object.entries(SPACE_VIEWS)) {
      expect(CONSOLE_SPACES.find((space) => space.slug === slug)?.views).toBe(views);
    }
  });

  it("reserva Ops a administradores", () => {
    expect(ADMIN_ONLY_SPACES.has("ops")).toBe(true);
    for (const slug of ADMIN_ONLY_SPACES) {
      expect(CONSOLE_SPACES.some((space) => space.slug === slug)).toBe(true);
    }
  });
});

describe("routeSlug", () => {
  it("se queda con el primer segmento", () => {
    expect(routeSlug("/mercado")).toBe("mercado");
    expect(routeSlug("mercado")).toBe("mercado");
    expect(routeSlug("/oportunidades/p-1")).toBe("oportunidades");
    expect(routeSlug("/competidores/empresa/42")).toBe("competidores");
  });

  it("descarta query y fragmento", () => {
    expect(routeSlug("/mercado?vista=geografia")).toBe("mercado");
    expect(routeSlug("/mercado#seccion")).toBe("mercado");
    expect(routeSlug("/mercado?vista=cpv#tabla")).toBe("mercado");
  });

  it("devuelve cadena vacía en la raíz", () => {
    expect(routeSlug("/")).toBe("");
    expect(routeSlug("")).toBe("");
  });
});

describe("findConsoleSpace", () => {
  it("encuentra el espacio de una ruta, con o sin subruta y query", () => {
    expect(findConsoleSpace("/radar")?.key).toBe("radar");
    expect(findConsoleSpace("/mercado?vista=organos")?.key).toBe("mercado");
    expect(findConsoleSpace("/oportunidades/p-1")?.key).toBe("oportunidades");
  });

  it("devuelve undefined para una ruta heredada o inexistente", () => {
    // `/tendencias` ya no es un espacio: es una vista de `/mercado`.
    expect(findConsoleSpace("/tendencias")).toBeUndefined();
    expect(findConsoleSpace("/no-existe")).toBeUndefined();
  });
});

describe("CONSOLE_ROUTES", () => {
  it("cubre los 13 espacios construidos", () => {
    expect(CONSOLE_ROUTES.size).toBe(BUILT_SPACE_ROUTES.length);
    for (const slug of BUILT_SPACE_ROUTES) {
      expect(CONSOLE_ROUTES.has(slug)).toBe(true);
    }
  });
});

describe("isSpaceImplemented / landingHref", () => {
  it("considera implementado todo espacio sin vistas", () => {
    const resumen = CONSOLE_SPACES.find((space) => space.key === "resumen")!;
    expect(resumen.views).toBeUndefined();
    expect(isSpaceImplemented(resumen)).toBe(true);
    expect(landingHref(resumen)).toBe("/resumen");
  });

  it("hoy tiene los 13 espacios implementados, así que el rail apunta a la ruta propia", () => {
    for (const space of CONSOLE_SPACES) {
      expect(isSpaceImplemented(space)).toBe(true);
      expect(landingHref(space)).toBe(`/${space.slug}`);
    }
  });

  it("un espacio con vistas pero sin ruta propia aterriza en la primera heredada", () => {
    // Simula el estado intermedio de la migración por lotes: mientras el
    // espacio no exista, el rail debe enlazar a una pantalla viva y no a un 404.
    const pendiente = {
      ...CONSOLE_SPACES.find((space) => space.key === "mercado")!,
      slug: "espacio-sin-construir",
    };
    expect(isSpaceImplemented(pendiente)).toBe(false);
    expect(landingHref(pendiente)).toBe("/tendencias");
  });

  it("cae a su propio slug si ninguna vista declara ruta heredada", () => {
    const sinFrom = {
      ...CONSOLE_SPACES.find((space) => space.key === "mercado")!,
      slug: "espacio-sin-construir",
      views: [{ key: "unica", label: "Única" }],
    };
    expect(landingHref(sinFrom)).toBe("/espacio-sin-construir");
  });
});

describe("LEGACY_REDIRECTS", () => {
  it("manda cada ruta absorbida a la vista que la sustituye", () => {
    expect(LEGACY_REDIRECTS).toHaveLength(17);
    expect(LEGACY_REDIRECTS).toContainEqual({
      from: "/competidores",
      to: "/competencia?vista=competidores",
    });
    expect(LEGACY_REDIRECTS).toContainEqual({
      from: "/renovaciones",
      to: "/mi-pipeline?vista=renovaciones",
    });
  });

  it("no colisiona con un espacio existente", () => {
    // Una ruta heredada que además fuese slug de espacio se redirigiría a sí
    // misma y entraría en bucle.
    const slugs = new Set(CONSOLE_SPACES.map((space) => space.slug));
    for (const { from } of LEGACY_REDIRECTS) {
      expect(slugs.has(from.replace(/^\//, ""))).toBe(false);
    }
  });
});

describe("spaceAbsorbing", () => {
  it("dice qué espacio y qué vista absorbieron una ruta heredada", () => {
    expect(spaceAbsorbing("tendencias-cpv")).toEqual({
      space: expect.objectContaining({ key: "mercado" }),
      view: "cpv",
    });
    expect(spaceAbsorbing("observabilidad")).toEqual({
      space: expect.objectContaining({ key: "ops" }),
      view: "observabilidad",
    });
  });

  it("devuelve undefined para una ruta que nadie absorbió", () => {
    expect(spaceAbsorbing("resumen")).toBeUndefined();
    expect(spaceAbsorbing("no-existe")).toBeUndefined();
  });

  it("resuelve las 17 rutas absorbidas hacia una vista real de su espacio", () => {
    for (const { from } of LEGACY_REDIRECTS) {
      const slug = from.replace(/^\//, "");
      const hit = spaceAbsorbing(slug);
      expect(hit, `sin espacio para ${slug}`).toBeDefined();
      expect(hit!.space.views?.some((view) => view.key === hit!.view)).toBe(true);
    }
  });
});
