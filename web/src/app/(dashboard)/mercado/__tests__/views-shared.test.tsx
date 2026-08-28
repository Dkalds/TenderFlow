/**
 * Las ocho vistas de Mercado viven en `_components/<x>-view.tsx` y las consumen
 * dos entradas: el espacio `/mercado` y el `page.tsx` de la ruta heredada.
 *
 * Este test fija dos cosas:
 *
 * 1. **La consolidación no eliminó nada.** Cada vista declarada en
 *    `SPACE_VIEWS.mercado` tiene su fichero de vista, su ruta heredada sigue
 *    existiendo como boundary y su redirect 308 sigue emitiéndose. Un enlace
 *    guardado a `/tendencias-cpv` tiene que seguir aterrizando en el análisis.
 * 2. **Ningún `page.tsx` importa otro `page.tsx`.** Mientras el espacio montaba
 *    los `page.tsx` de las rutas, cada uno era boundary de ruta y componente a
 *    la vez: dos puntos de entrada, dos estados de URL, y Next sin poder
 *    tratarlos como lo primero. La comprobación se hace sobre todo el árbol de
 *    `app/`, no sólo sobre Mercado, porque el patrón se repitió en cuatro
 *    espacios y volvería a colarse en el siguiente.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, it, expect } from "vitest";

import { SPACE_VIEWS, legacyRedirects } from "@/lib/space-views";

import { metadata as tendenciasMeta } from "../../tendencias/layout";
import { metadata as tendenciasCpvMeta } from "../../tendencias-cpv/layout";
import { metadata as calendarioMeta } from "../../calendario/layout";
import { metadata as geografiaMeta } from "../../geografia/layout";
import { metadata as tecnologiasMeta } from "../../tecnologias/layout";
import { metadata as organosMeta } from "../../organos/layout";
import { metadata as clustersMeta } from "../../clusters/layout";
import { metadata as proyectosMeta } from "../../proyectos-modulos/layout";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MERCADO_DIR = path.resolve(HERE, "..");
const DASHBOARD_DIR = path.resolve(MERCADO_DIR, "..");
const APP_DIR = path.resolve(DASHBOARD_DIR, "..");

/** ruta heredada → fichero de vista compartida que debe montar. */
const ROUTES: Record<string, string> = {
  tendencias: "tendencias-view",
  "tendencias-cpv": "tendencias-cpv-view",
  calendario: "calendario-view",
  geografia: "geografia-view",
  tecnologias: "tecnologias-view",
  organos: "organos-view",
  clusters: "clusters-view",
  "proyectos-modulos": "proyectos-modulos-view",
};

/** `?vista=` del espacio → ruta heredada que absorbe. */
const VISTA_POR_RUTA: Record<string, string> = {
  tendencias: "tiempo",
  "tendencias-cpv": "cpv",
  calendario: "calendario",
  geografia: "geografia",
  tecnologias: "tecnologias",
  organos: "organos",
  clusters: "clusters",
  "proyectos-modulos": "proyectos",
};

const read = (...segments: string[]): string => readFileSync(path.join(...segments), "utf8");

/**
 * Espacios que todavía montan el `page.tsx` de sus rutas heredadas. No es una
 * lista de excepciones permanentes: es la deuda que queda por saldar con el
 * mismo movimiento que Ops y Mercado ya hicieron. La aserción es de
 * *subconjunto*, así que arreglar uno no rompe este test — sólo aparecer uno
 * nuevo lo hace.
 */
const DEUDA_CONOCIDA = new Set(["competencia/page.tsx", "mi-pipeline/page.tsx"]);

/** Todos los `page.tsx` bajo `app/`, en ruta relativa POSIX. */
function pageFiles(dir: string, base = dir): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry === "__tests__") continue;
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...pageFiles(full, base));
    } else if (entry === "page.tsx") {
      out.push(path.relative(base, full).split(path.sep).join("/"));
    }
  }
  return out;
}

/**
 * ¿Este fuente importa el módulo `page` de otra ruta? Cubre las dos formas:
 * `import X from ".../page"` y el `import(".../page")` de `next/dynamic`.
 */
function importaUnPage(source: string): boolean {
  return /from\s+["'][^"']*\/page["']/.test(source) || /import\(["'][^"']*\/page["']\)/.test(source);
}

describe("vistas de Mercado — módulo compartido", () => {
  it("mercado/page.tsx no importa ningún page.tsx", () => {
    expect(importaUnPage(read(MERCADO_DIR, "page.tsx"))).toBe(false);
  });

  it("mercado/page.tsx monta las ocho vistas desde _components", () => {
    const source = read(MERCADO_DIR, "page.tsx");
    for (const view of Object.values(ROUTES)) {
      expect(source).toContain(`./_components/${view}`);
    }
  });

  it.each(Object.entries(ROUTES))("la ruta /%s monta la misma vista compartida", (route, view) => {
    const source = read(DASHBOARD_DIR, route, "page.tsx");
    expect(source).toContain(`../mercado/_components/${view}`);
  });

  it("cada ruta conserva su metadata.title", () => {
    expect(tendenciasMeta.title).toBe("Tendencias");
    expect(tendenciasCpvMeta.title).toBe("Tendencias CPV");
    expect(calendarioMeta.title).toBe("Calendario");
    expect(geografiaMeta.title).toBe("Geografía");
    expect(tecnologiasMeta.title).toBe("Tecnologías");
    expect(organosMeta.title).toBe("Órganos");
    expect(clustersMeta.title).toBe("Clusters");
    expect(proyectosMeta.title).toBe("Proyectos y Modulos");
  });
});

describe("consolidar no elimina funcionalidad", () => {
  it("las ocho vistas del espacio siguen teniendo su ruta heredada alcanzable", () => {
    const redirects = new Map(legacyRedirects().map((r) => [r.source, r.destination]));

    for (const view of SPACE_VIEWS.mercado) {
      expect(view.from, `la vista ${view.key} debería absorber una ruta`).toBeDefined();
      const route = view.from!;

      // Sigue existiendo el boundary: borrar la ruta heredada rompería los
      // enlaces guardados aunque el redirect siguiera declarado.
      expect(() => read(DASHBOARD_DIR, route, "page.tsx")).not.toThrow();
      // Y el 308 sigue llevándola a su `?vista=` dentro del espacio.
      expect(redirects.get(`/${route}`)).toBe(`/mercado?vista=${VISTA_POR_RUTA[route]}`);
    }
  });
});

describe("invariante de árbol: ningún page.tsx importa otro page.tsx", () => {
  it("sólo la deuda ya registrada incumple", () => {
    const ofensores = pageFiles(APP_DIR).filter((relative) => importaUnPage(read(APP_DIR, relative)));

    // Subconjunto, no igualdad: cuando otro espacio salde su deuda este test
    // sigue verde. Lo que no puede pasar es que aparezca un ofensor nuevo.
    const nuevos = ofensores.filter((relative) => {
      const dentroDelGrupo = relative.replace(/^\([^)]*\)\//, "");
      return !DEUDA_CONOCIDA.has(dentroDelGrupo);
    });

    expect(nuevos).toEqual([]);
  });
});
