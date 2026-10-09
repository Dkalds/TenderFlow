import { describe, it, expect } from "vitest";
import {
  ADMIN_ONLY_SPACES,
  CONSOLE_GROUP_ORDER,
  CONSOLE_ROUTES,
  CONSOLE_SPACES,
  findConsoleSpace,
  isSpaceImplemented,
  landingHref,
  routeSlug,
  spaceAbsorbing,
} from "@/lib/console-spaces";
import { legacyRedirects, VISTAS_FUSIONADAS } from "@/lib/space-views";
import { ICONO_ESPACIO } from "@/lib/iconos";
import { BUILT_SPACE_ROUTES, SPACE_VIEWS } from "@/lib/space-views";

describe("CONSOLE_SPACES", () => {
  // 14 → 16 el 2026-09-06 (plan de funcionalidades) y 17 con `ajustes` (C7.5).
  // La condición para añadir espacio no ha cambiado: cada uno **absorbe** una
  // vista existente —Cuentas absorbe `Mercado → Órganos`, Ajustes absorbe
  // `/mi-cuenta`— y ninguna desaparece de su sitio original, porque consolidar
  // no elimina. Un espacio que sólo fuera un corte analítico más no entraría:
  // eso es lo que el plan descarta. Dirección nació para absorber el embudo de
  // Mi Pipeline y añadirle cortes; la reestructura 2026-09-20 retiró su vista
  // `embudo` (un `EmptyState` sin función) y el embudo vive en
  // `Oportunidades → Rendimiento`.
  it("consolida las rutas del dashboard, y cada absorbida una sola vez", () => {
    // El recuento se **deriva**. Fijarlo a mano obliga a tocar el test cada vez
    // que un espacio absorbe una ruta, y no dice nada que las tablas no digan.
    // Lo que sí hay que sostener: ningún espacio se queda sin slug y ninguna
    // ruta heredada la reclaman dos, porque el redirect ganador sería el del
    // orden de declaración.
    expect(CONSOLE_SPACES.length).toBeGreaterThan(0);
    const absorbed = CONSOLE_SPACES.flatMap((space) => space.views ?? []).filter(
      (view) => view.from,
    );
    expect(new Set(absorbed.map((view) => view.from)).size).toBe(absorbed.length);
  });

  it("da a cada espacio clave, slug y nombre únicos", () => {
    const keys = CONSOLE_SPACES.map((space) => space.key);
    const slugs = CONSOLE_SPACES.map((space) => space.slug);
    const labels = CONSOLE_SPACES.map((space) => space.label);
    expect(new Set(keys).size).toBe(keys.length);
    expect(new Set(slugs).size).toBe(slugs.length);
    // El rail pinta el nombre bajo el icono: dos iguales no se distinguirían.
    expect(new Set(labels).size).toBe(labels.length);
    for (const space of CONSOLE_SPACES) {
      expect(space.label.length).toBeGreaterThan(0);
      expect(space.description.length).toBeGreaterThan(0);
    }
  });

  it("no lleva códigos de tres letras: el rail pinta el nombre del espacio", () => {
    // RES, MKT, OPS/OPX… eran abreviaturas que había que aprenderse, mitad en
    // inglés, y con choques. El campo `short` ya no existe.
    for (const space of CONSOLE_SPACES) {
      expect(space).not.toHaveProperty("short");
    }
  });

  it("da a cada espacio un icono propio, el del mapa de `lib/iconos.ts`", () => {
    // Resumen y Dirección compartían LayoutDashboard, Cuentas y Empresas
    // Building2, Ajustes y Ops ShieldCheck.
    expect(new Set(CONSOLE_SPACES.map((space) => space.icon)).size).toBe(CONSOLE_SPACES.length);
    for (const space of CONSOLE_SPACES) {
      expect(space.icon, space.key).toBe(ICONO_ESPACIO[space.key as keyof typeof ICONO_ESPACIO]);
    }
  });

  it("describe cada espacio por el trabajo que resuelve, no por cómo está hecho", () => {
    // Las descripciones se ven junto al título, en el tooltip del rail y en la
    // paleta: sin jerga de implementación ni roles en inglés.
    const jerga = /backend|endpoint|servidor|corpus|sem[aá]ntic|tabla de|inspector|cortes|owner|admin\b|keyword|scoring/i;
    for (const space of CONSOLE_SPACES) {
      expect(space.description, space.key).not.toMatch(jerga);
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

// La tabla de redirects vive en `lib/space-views.ts` (la consume
// `next.config.ts`); aquí se comprueba contra los espacios de la consola.
const LEGACY_REDIRECTS = legacyRedirects().map(({ source, destination }) => ({ from: source, to: destination }));

describe("legacyRedirects frente a los espacios", () => {
  it("manda cada ruta absorbida a la vista que la sustituye", () => {
    // Derivado de las tablas, no fijado a mano: un literal aquí obliga a tocar
    // el test cada vez que un espacio absorbe una ruta.
    const absorbidas = CONSOLE_SPACES.flatMap((space) => space.views ?? []).filter(
      (view) => view.from,
    );
    // Más las de las vistas que se fundieron en otra: su ruta sigue redirigiendo.
    const fusionadas = Object.values(VISTAS_FUSIONADAS)
      .flat()
      .filter((vista) => vista.from);
    expect(LEGACY_REDIRECTS).toHaveLength(absorbidas.length + fusionadas.length);
    expect(LEGACY_REDIRECTS).toContainEqual({
      from: "/competidores",
      to: "/competencia?vista=competidores",
    });
    // C7.5: `/mi-cuenta` la absorbe Ajustes, y su `page.tsx` se retiró — un
    // `page.tsx` bajo un 308 se compila y no se ejecuta nunca.
    expect(LEGACY_REDIRECTS).toContainEqual({
      from: "/mi-cuenta",
      to: "/ajustes?vista=cuenta",
    });
    expect(LEGACY_REDIRECTS).toContainEqual({
      from: "/pipeline-alertas",
      to: "/mi-pipeline?vista=agenda",
    });
    // Reestructura 2026-09-20: las renovaciones son una vista de Mercado, así
    // que `/renovaciones` cambia de destino sin dejar de redirigir. El
    // `?vista=horizonte` viejo de `/mi-pipeline` lo reenvía su página.
    expect(LEGACY_REDIRECTS).toContainEqual({
      from: "/renovaciones",
      to: "/mercado?vista=renovaciones",
    });
    expect(LEGACY_REDIRECTS.some((redirect) => redirect.to.startsWith("/mi-pipeline?vista=horizonte"))).toBe(
      false,
    );
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

  it("la ruta de una vista que se fundió en otra resuelve a la vista donde vive hoy", () => {
    // `/feature-flags` fue una vista propia de Ops y hoy es una sección de
    // Administración. El rail sigue teniendo que saber de qué espacio es, y la
    // vista que devuelve tiene que existir: `flags` ya no es ninguna.
    expect(spaceAbsorbing("feature-flags")).toEqual({
      space: expect.objectContaining({ key: "ops" }),
      view: "administracion",
    });
    expect(spaceAbsorbing("webhooks")).toEqual({
      space: expect.objectContaining({ key: "ops" }),
      view: "administracion",
    });
  });

  it("devuelve undefined para una ruta que nadie absorbió", () => {
    expect(spaceAbsorbing("resumen")).toBeUndefined();
    expect(spaceAbsorbing("no-existe")).toBeUndefined();
  });

  it("resuelve todas las rutas absorbidas hacia una vista real de su espacio", () => {
    for (const { from } of LEGACY_REDIRECTS) {
      const slug = from.replace(/^\//, "");
      const hit = spaceAbsorbing(slug);
      expect(hit, `sin espacio para ${slug}`).toBeDefined();
      expect(hit!.space.views?.some((view) => view.key === hit!.view)).toBe(true);
    }
  });
});
