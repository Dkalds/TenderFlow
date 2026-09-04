import { readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { proxy } from "@/proxy";
import robots from "@/app/robots";
import {
  PAGINAS_PUBLICAS,
  esPaginaPublica,
  paginasDeSitemap,
  rutasRastreables,
} from "@/lib/rutas-publicas";

/**
 * El test que faltaba cuando se publicaron tres páginas muertas.
 *
 * `/cobertura`, `/metodologia` y `/seguridad` se escribieron enteras dentro del
 * grupo `(publico)` y se desplegaron devolviendo un 307 a `/login`: nadie las
 * había añadido a las listas del proxy, de robots ni del sitemap, y no existía
 * nada que comparase una cosa con la otra. Estar en `(publico)` era una
 * intención, no un hecho comprobado.
 *
 * Aquí el árbol de ficheros es la fuente: se enumeran los `page.tsx` reales y
 * se exige que cada uno sea de verdad alcanzable sin sesión. Una página nueva
 * que nadie declare hace fallar esta suite, que es exactamente cuando conviene
 * enterarse.
 */

const RAIZ_APP = path.resolve(__dirname, "..", "app");

/** Valor con el que se sustituye un segmento dinámico para poder pedir la URL. */
const EJEMPLOS: Record<string, string> = {
  "[ccaa]": "cataluna",
  "[slug]": "servicios-de-desarrollo",
  "[ref]": "EXP-2026-1",
  "[codigo]": "72000000",
};

/**
 * Rutas servibles del App Router, leídas del disco.
 *
 * Los grupos de rutas —`(publico)`, `(dashboard)`— organizan ficheros y no
 * aparecen en la URL, así que se descartan; los segmentos dinámicos se
 * sustituyen por un valor plausible para poder pasar la ruta por el proxy.
 */
function rutasDePaginas(dir: string, prefijo = ""): { ruta: string; grupo: string | null }[] {
  const encontradas: { ruta: string; grupo: string | null }[] = [];

  for (const entrada of readdirSync(dir, { withFileTypes: true })) {
    if (entrada.isDirectory()) {
      // `_components`, `_content`, `_assets`, `__tests__`: convención de Next
      // para lo que no es una ruta.
      if (entrada.name.startsWith("_")) continue;
      const esGrupo = entrada.name.startsWith("(") && entrada.name.endsWith(")");
      const segmento = esGrupo ? "" : `/${EJEMPLOS[entrada.name] ?? entrada.name}`;
      encontradas.push(...rutasDePaginas(path.join(dir, entrada.name), prefijo + segmento));
    } else if (entrada.name === "page.tsx") {
      const grupo = dir.match(/\(([^)]+)\)/)?.[1] ?? null;
      encontradas.push({ ruta: prefijo === "" ? "/" : prefijo, grupo });
    }
  }

  return encontradas;
}

const PAGINAS_EN_DISCO = rutasDePaginas(RAIZ_APP);
const PAGINAS_DEL_GRUPO_PUBLICO = PAGINAS_EN_DISCO.filter((p) => p.grupo === "publico");

function destino(ruta: string): string | null {
  return proxy(new NextRequest(new URL(`https://tenderflow.es${ruta}`))).headers.get("location");
}

describe("el grupo (publico) es público de verdad", () => {
  it("encuentra las páginas en disco", () => {
    // Si el recorrido dejara de encontrar ficheros, los `it.each` de abajo se
    // quedarían vacíos y la suite pasaría sin comprobar nada.
    expect(PAGINAS_DEL_GRUPO_PUBLICO.length).toBeGreaterThanOrEqual(8);
  });

  it.each(PAGINAS_DEL_GRUPO_PUBLICO.map((p) => p.ruta))("%s se sirve sin sesión", (ruta) => {
    expect(destino(ruta)).toBeNull();
  });

  it.each(PAGINAS_DEL_GRUPO_PUBLICO.map((p) => p.ruta))("%s está declarada pública", (ruta) => {
    expect(esPaginaPublica(ruta)).toBe(true);
  });
});

describe("la lista y el disco no divergen", () => {
  it("cada ruta declarada corresponde a una página que existe", () => {
    // El error simétrico del anterior: anunciar en el sitemap o abrir en el
    // proxy una ruta que ya no tiene fichero detrás.
    const enDisco = PAGINAS_EN_DISCO.map((p) => p.ruta);
    for (const pagina of PAGINAS_PUBLICAS) {
      const existe = enDisco.some((ruta) =>
        pagina.coincidencia === "exacta" ? ruta === pagina.ruta : ruta.startsWith(pagina.ruta),
      );
      expect(existe, `${pagina.ruta} no tiene page.tsx`).toBe(true);
    }
  });
});

describe("robots y sitemap salen de la misma lista", () => {
  it("robots permite todo lo declarado rastreable", () => {
    const permitidas = robots().rules;
    const allow = Array.isArray(permitidas) ? [] : ((permitidas.allow as string[]) ?? []);
    expect(allow).toEqual(rutasRastreables());
  });

  it.each(["/cpvfoo", "/licitacionesx", "/loginfalso", "/aviso-legal-falso"])(
    "%s no se cuela como pública por empezar igual que un prefijo",
    (ruta) => {
      // `startsWith` a secas abría estas cuatro: rutas que no existen, servidas
      // como públicas y resueltas por el 404 raíz en vez de por el del grupo.
      expect(esPaginaPublica(ruta)).toBe(false);
    },
  );

  it.each(["/licitaciones/cataluna", "/licitaciones/cataluna/algo/EXP-1", "/cpv/72000000"])(
    "%s sigue siendo pública, que es lo que el prefijo debe abrir",
    (ruta) => {
      expect(esPaginaPublica(ruta)).toBe(true);
    },
  );

  it("la portada se abre anclada, para no abrir el dashboard entero", () => {
    // `Allow: /` anularía el `Disallow: /` y expondría las 36 rutas privadas.
    expect(rutasRastreables()).toContain("/$");
    expect(rutasRastreables()).not.toContain("/");
  });

  it.each(["/cobertura", "/metodologia", "/seguridad"])(
    "%s se rastrea y se anuncia en el sitemap",
    (ruta) => {
      expect(rutasRastreables()).toContain(ruta);
      expect(paginasDeSitemap().map((p) => p.ruta)).toContain(ruta);
    },
  );

  it("el sitemap no anuncia nada que robots bloquee", () => {
    // Una URL anunciada y bloqueada es un error de cobertura en Search Console.
    const rastreables = rutasRastreables();
    for (const pagina of paginasDeSitemap()) {
      expect(rastreables).toContain(pagina.ruta === "/" ? "/$" : pagina.ruta);
    }
  });
});
