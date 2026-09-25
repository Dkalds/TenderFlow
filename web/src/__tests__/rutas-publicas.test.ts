import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { proxy } from "@/proxy";
import robots from "@/app/robots";
import { PREFIJO_PAGINACION_INTERNA, destinoPaginaInterna, esRutaPaginacionInterna } from "@/lib/paginacion-hubs";
import {
  PAGINAS_PUBLICAS,
  esPaginaPrerenderizada,
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
  "[pagina]": "2",
};

interface PaginaEnDisco {
  ruta: string;
  grupo: string | null;
  fichero: string;
  /** Algún segmento de su ruta es dinámico (`[ccaa]`, `[pagina]`…). */
  dinamica: boolean;
}

/**
 * Rutas servibles del App Router, leídas del disco.
 *
 * Los grupos de rutas —`(publico)`, `(dashboard)`— organizan ficheros y no
 * aparecen en la URL, así que se descartan; los segmentos dinámicos se
 * sustituyen por un valor plausible para poder pasar la ruta por el proxy.
 */
function rutasDePaginas(dir: string, prefijo = "", dinamica = false): PaginaEnDisco[] {
  const encontradas: PaginaEnDisco[] = [];

  for (const entrada of readdirSync(dir, { withFileTypes: true })) {
    if (entrada.isDirectory()) {
      // `_components`, `_content`, `_assets`, `__tests__`: convención de Next
      // para lo que no es una ruta.
      if (entrada.name.startsWith("_")) continue;
      const esGrupo = entrada.name.startsWith("(") && entrada.name.endsWith(")");
      const segmento = esGrupo ? "" : `/${EJEMPLOS[entrada.name] ?? entrada.name}`;
      const esDinamico = entrada.name.startsWith("[");
      encontradas.push(...rutasDePaginas(path.join(dir, entrada.name), prefijo + segmento, dinamica || esDinamico));
    } else if (entrada.name === "page.tsx") {
      const grupo = dir.match(/\(([^)]+)\)/)?.[1] ?? null;
      encontradas.push({
        ruta: prefijo === "" ? "/" : prefijo,
        grupo,
        fichero: path.join(dir, entrada.name),
        dinamica,
      });
    }
  }

  return encontradas;
}

const PAGINAS_EN_DISCO = rutasDePaginas(RAIZ_APP);
const PAGINAS_DEL_GRUPO_PUBLICO = PAGINAS_EN_DISCO.filter((p) => p.grupo === "publico");
/**
 * Las páginas que se sirven por su propia URL. Las del árbol interno de
 * paginación viven en `(publico)` porque comparten layout y 404 con los hubs,
 * pero solo se alcanzan por el rewrite del proxy: tienen su propio bloque abajo.
 */
const PAGINAS_SERVIDAS = PAGINAS_DEL_GRUPO_PUBLICO.filter((p) => !esRutaPaginacionInterna(p.ruta));
const PAGINAS_INTERNAS = PAGINAS_DEL_GRUPO_PUBLICO.filter((p) => esRutaPaginacionInterna(p.ruta));

function responder(ruta: string): Response {
  return proxy(new NextRequest(new URL(`https://tenderflow.es${ruta}`)));
}

function destino(ruta: string): string | null {
  return responder(ruta).headers.get("location");
}

describe("el grupo (publico) es público de verdad", () => {
  it("encuentra las páginas en disco", () => {
    // Si el recorrido dejara de encontrar ficheros, los `it.each` de abajo se
    // quedarían vacíos y la suite pasaría sin comprobar nada.
    expect(PAGINAS_SERVIDAS.length).toBeGreaterThanOrEqual(8);
  });

  it.each(PAGINAS_SERVIDAS.map((p) => p.ruta))("%s se sirve sin sesión", (ruta) => {
    expect(destino(ruta)).toBeNull();
  });

  it.each(PAGINAS_SERVIDAS.map((p) => p.ruta))("%s está declarada pública", (ruta) => {
    expect(esPaginaPublica(ruta)).toBe(true);
  });
});

describe("el árbol interno de paginación", () => {
  // Los hubs públicos que paginan con `?p=N`, con los segmentos de `EJEMPLOS`.
  // Escritos a mano a propósito: si aparece una ruta estática nueva junto a
  // `[ccaa]` (como `organo`) y el patrón del hub por comunidad la captura, esta
  // lista deja de coincidir y el test lo dice, en vez de que esa página pase a
  // responder 404 en cuanto alguien le añada `?p=2`.
  const HUBS_QUE_PAGINAN = ["/cpv/72000000", "/licitaciones/cataluna", "/licitaciones/organo/servicios-de-desarrollo"];

  it("el proxy pagina exactamente los tres hubs, y cada uno tiene su página interna", () => {
    const paginadas = PAGINAS_SERVIDAS.flatMap((p) => {
      const interna = destinoPaginaInterna(p.ruta, new URLSearchParams("p=2"));
      return interna ? [{ publica: p.ruta, interna }] : [];
    });

    expect(paginadas.map((p) => p.publica).sort()).toEqual(HUBS_QUE_PAGINAN);
    for (const { interna } of paginadas) {
      expect(
        PAGINAS_INTERNAS.map((p) => p.ruta),
        `falta la página interna ${interna}`,
      ).toContain(interna);
    }
  });

  it.each(PAGINAS_INTERNAS.map((p) => p.ruta))("%s replica un hub que existe", (ruta) => {
    // `/hub-paginado/cpv/72000000/2` sirve `/cpv/72000000?p=2`: sin prefijo y
    // sin número tiene que quedar un hub del disco, y el proxy tiene que
    // reescribir su `?p=2` justo aquí. Una página interna huérfana nunca se
    // alcanzaría.
    const publica = ruta.slice(PREFIJO_PAGINACION_INTERNA.length).replace(/\/2$/, "");
    expect(HUBS_QUE_PAGINAN).toContain(publica);
    expect(destinoPaginaInterna(publica, new URLSearchParams("p=2"))).toBe(ruta);
  });

  it.each(PAGINAS_INTERNAS.map((p) => p.ruta))("%s no se sirve por su propia URL", (ruta) => {
    // Servida directamente sería la misma página bajo una segunda URL.
    const respuesta = responder(ruta);
    expect(respuesta.status).toBe(404);
    expect(respuesta.headers.get("location")).toBeNull();
  });

  it("ni robots la abre ni el sitemap la anuncia", () => {
    expect(PAGINAS_INTERNAS.length).toBeGreaterThanOrEqual(3);
    for (const { ruta } of PAGINAS_INTERNAS) {
      // `Allow:` casa por prefijo; `/$` solo la portada.
      const abierta = rutasRastreables().some((allow) => (allow === "/$" ? ruta === "/" : ruta.startsWith(allow)));
      expect(abierta, `${ruta} queda rastreable`).toBe(false);
      expect(esPaginaPublica(ruta)).toBe(false);
    }
    expect(paginasDeSitemap().some((p) => esRutaPaginacionInterna(p.ruta))).toBe(false);
  });
});

/** El código sin comentarios: aquí se explica mucho, y citar una API no es usarla. */
function sinComentarios(codigo: string): string {
  return codigo.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

describe("lo prerenderizado se puede cachear de verdad", () => {
  // El fallo que caza: los hubs y la ficha declaraban `revalidate = 3600` y se
  // renderizaban en cada petición. En Next 16 leer `searchParams` o
  // `next/headers` obliga a renderizar en dinámico, y una ruta dinámica sin
  // `generateStaticParams` también; `revalidate` no avisa de nada. Sin build
  // no hay `prerender-manifest` que mirar, así que se lee el fuente de cada
  // página que debería salir de la caché: las declaradas `prerenderizada` y
  // las internas de paginación.
  const CACHEABLES = PAGINAS_DEL_GRUPO_PUBLICO.filter(
    (p) => esPaginaPrerenderizada(p.ruta) || esRutaPaginacionInterna(p.ruta),
  );

  it("encuentra las páginas que comprobar", () => {
    expect(CACHEABLES.length).toBeGreaterThanOrEqual(12);
  });

  it.each(CACHEABLES.map((p) => [p.ruta, p.fichero]))("%s no lee la query ni las cabeceras", (_ruta, fichero) => {
    const codigo = sinComentarios(readFileSync(fichero, "utf8"));
    expect(codigo).not.toMatch(/\bsearchParams\b/);
    expect(codigo).not.toMatch(/from\s+["']next\/headers["']/);
  });

  it.each(CACHEABLES.filter((p) => p.dinamica).map((p) => [p.ruta, p.fichero]))(
    "%s declara generateStaticParams, o no pasaría por la caché",
    (_ruta, fichero) => {
      const codigo = sinComentarios(readFileSync(fichero, "utf8"));
      expect(codigo).toMatch(/export\s+(?:async\s+)?function\s+generateStaticParams\b/);
      expect(codigo).toMatch(/export\s+const\s+revalidate\s*=\s*3600\b/);
    },
  );
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

  it.each(["/cobertura", "/metodologia", "/seguridad"])("%s se rastrea y se anuncia en el sitemap", (ruta) => {
    expect(rutasRastreables()).toContain(ruta);
    expect(paginasDeSitemap().map((p) => p.ruta)).toContain(ruta);
  });

  it("el sitemap no anuncia nada que robots bloquee", () => {
    // Una URL anunciada y bloqueada es un error de cobertura en Search Console.
    const rastreables = rutasRastreables();
    for (const pagina of paginasDeSitemap()) {
      expect(rastreables).toContain(pagina.ruta === "/" ? "/$" : pagina.ruta);
    }
  });
});
