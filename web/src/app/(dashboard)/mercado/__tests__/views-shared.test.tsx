/**
 * Las ocho vistas de Mercado viven en `_components/<x>-view.tsx` y las monta
 * una sola entrada: el espacio `/mercado`.
 *
 * Hasta 2026-09 cada vista tenía además un `page.tsx` de ruta heredada que la
 * re-exportaba, y este test exigía que ese boundary siguiera existiendo «porque
 * borrarlo rompería los enlaces guardados». Era falso, y por eso se cambia: los
 * `redirects()` de `next.config.ts` se resuelven ANTES del enrutado por sistema
 * de ficheros, así que `/tendencias` nunca llegaba a montar su `page.tsx` — el
 * 308 la interceptaba siempre. Aquellos catorce ficheros no eran una red de
 * seguridad para los marcadores, eran código que se compilaba y no se ejecutaba,
 * y este test los fijaba en su sitio.
 *
 * Lo que sí preserva un enlace guardado es el redirect. El test lo comprueba
 * ahora de forma explícita y añade la mitad que faltaba: que la ruta absorbida
 * **no** vuelva a existir como directorio, porque un `page.tsx` a la sombra de
 * un 308 es inalcanzable por construcción.
 *
 * Se conservan los dos invariantes originales:
 *
 * 1. **La consolidación no elimina nada.** Cada vista declarada en
 *    `SPACE_VIEWS.mercado` tiene su fichero, el espacio la monta y su ruta
 *    heredada sigue llevando al mismo análisis.
 * 2. **Ningún `page.tsx` importa otro `page.tsx`.** Mientras el espacio montaba
 *    los `page.tsx` de las rutas, cada uno era boundary de ruta y componente a
 *    la vez: dos puntos de entrada, dos estados de URL, y Next sin poder
 *    tratarlos como lo primero (un componente montado a mano no recibe el
 *    contrato `params`/`searchParams`). La comprobación se hace sobre todo el
 *    árbol de `app/`, no sólo sobre Mercado, porque el patrón se repitió en
 *    cuatro espacios y volvería a colarse en el siguiente.
 */
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, it, expect } from "vitest";

import { SPACE_VIEWS, legacyRedirects } from "@/lib/space-views";

import { metadata as mercadoMeta } from "../layout";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MERCADO_DIR = path.resolve(HERE, "..");
const DASHBOARD_DIR = path.resolve(MERCADO_DIR, "..");
const APP_DIR = path.resolve(DASHBOARD_DIR, "..");

/** ruta absorbida → fichero de vista en `_components` que la sustituye. */
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

/** ruta absorbida → `?vista=` del espacio que la sirve hoy. */
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

  it.each(Object.entries(ROUTES))("la vista de /%s existe en _components", (_route, view) => {
    expect(existsSync(path.join(MERCADO_DIR, "_components", `${view}.tsx`))).toBe(true);
  });

  it("el espacio tiene título de documento propio", () => {
    // Las ocho rutas absorbidas lo tenían en su layout; al retirarlas, el único
    // título que se llega a emitir es el del espacio (WCAG 2.2 §2.4.2).
    expect(mercadoMeta.title).toBe("Mercado");
  });
});

describe("consolidar no elimina funcionalidad", () => {
  it("cada vista del espacio declara la ruta que absorbe", () => {
    for (const view of SPACE_VIEWS.mercado) {
      expect(view.from, `la vista ${view.key} debería absorber una ruta`).toBeDefined();
    }
  });

  it("el 308 de cada ruta absorbida sigue llevando a su ?vista=", () => {
    // Esto —y sólo esto— es lo que mantiene vivo un marcador de `/geografia`.
    const redirects = new Map(legacyRedirects().map((r) => [r.source, r.destination]));

    for (const route of Object.keys(ROUTES)) {
      expect(redirects.get(`/${route}`)).toBe(`/mercado?vista=${VISTA_POR_RUTA[route]}`);
    }
  });

  it.each(Object.keys(ROUTES))(
    "/%s no vuelve a existir como ruta a la sombra de su redirect",
    (route) => {
      // Un `page.tsx` bajo una ruta redirigida no se puede alcanzar: el redirect
      // gana. Reintroducirlo sólo añade código que se compila y no se ejecuta.
      expect(existsSync(path.join(DASHBOARD_DIR, route))).toBe(false);
    },
  );
});

describe("invariante de árbol: ningún page.tsx importa otro page.tsx", () => {
  it("no queda ninguno", () => {
    // Ratchet: el valor medido tras mover Competencia y Mi Pipeline a
    // `_components` es cero. Sólo puede encoger — nunca se sube el listón para
    // acomodar un ofensor nuevo.
    const ofensores = pageFiles(APP_DIR).filter((relative) => importaUnPage(read(APP_DIR, relative)));

    expect(ofensores).toEqual([]);
  });
});
