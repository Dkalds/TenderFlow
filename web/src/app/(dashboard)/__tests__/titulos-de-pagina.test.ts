import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { CONSOLE_SPACES } from "@/lib/console-spaces";
import { legacyRedirects } from "@/lib/space-views";

/**
 * Toda ruta del dashboard tiene título de documento.
 *
 * WCAG 2.2 §2.4.2 «Página titulada», nivel A. El patrón del repo es un
 * `layout.tsx` de cuatro líneas por ruta que declara `metadata.title`, y estaba
 * aplicado en 25 de 34: faltaba justo en Radar y Oportunidades, las dos
 * pantallas insignia, que heredaban el `default` del layout raíz. En la
 * práctica la pestaña, el marcador, el historial y el anuncio del lector de
 * pantalla decían "TenderFlow" en todas.
 *
 * El test recorre el árbol en vez de listar rutas: una ruta nueva sin título
 * falla aquí el día que se crea, no cuando alguien la audita. Se mantiene ese
 * recorrido a propósito —cambiarlo por la lista de `console-spaces.ts` habría
 * dejado escapar justo el caso que este test existe para cazar: la ruta que
 * alguien añade al árbol sin registrarla en ninguna tabla—. Lo que sí se añade
 * es la mitad que faltaba, y que hasta 2026-09 hacía de este test un ancla de
 * código muerto: exigía título a diecisiete rutas que **no se podían alcanzar**
 * porque `next.config.ts` las redirige con un 308 permanente, y los redirects
 * de Next se resuelven antes que el enrutado por sistema de ficheros. Ahora una
 * ruta a la sombra de su propio redirect falla en vez de pedir metadata.
 */

const RAIZ = join(__dirname, "..");

/** Directorios que no son rutas navegables. */
const IGNORAR = new Set(["__tests__", "_components", "_hooks", "_assets"]);

function rutasConPagina(dir: string, relativa = ""): string[] {
  const encontradas: string[] = [];
  for (const entrada of readdirSync(dir)) {
    const completa = join(dir, entrada);
    if (!statSync(completa).isDirectory()) continue;
    if (IGNORAR.has(entrada)) continue;
    const rel = relativa ? `${relativa}/${entrada}` : entrada;
    if (readdirSync(completa).includes("page.tsx")) encontradas.push(rel);
    encontradas.push(...rutasConPagina(completa, rel));
  }
  return encontradas;
}

function declaraTitulo(ruta: string): boolean {
  const dir = join(RAIZ, ...ruta.split("/"));
  if (!readdirSync(dir).includes("layout.tsx")) return false;
  const fuente = readFileSync(join(dir, "layout.tsx"), "utf8");
  // Estático (`title: "…"`) o derivado de los params (`generateMetadata`).
  return /title\s*:/.test(fuente) || /generateMetadata/.test(fuente);
}

describe("títulos de documento del dashboard", () => {
  const rutas = rutasConPagina(RAIZ);

  it("hay rutas que comprobar", () => {
    // Si el recorrido devolviera 0, todo lo de abajo pasaría sin probar nada.
    // El suelo sale de `console-spaces.ts` en vez de ser un número a mano: cada
    // espacio de la consola es una ruta, así que nunca puede haber menos.
    expect(rutas.length).toBeGreaterThanOrEqual(CONSOLE_SPACES.length);
  });

  it.each(CONSOLE_SPACES.map((espacio) => espacio.slug))(
    "el espacio /%s existe como ruta",
    (slug) => {
      // La otra dirección del recorrido: el rail enlaza a estos catorce slugs,
      // así que ninguno puede quedarse sin `page.tsx` propio.
      expect(rutas).toContain(slug);
    },
  );

  it.each(rutas)("/%s declara metadata.title", (ruta) => {
    expect(declaraTitulo(ruta)).toBe(true);
  });

  it.each(rutas)("/%s es alcanzable (ningún 308 la tapa)", (ruta) => {
    // Un `page.tsx` bajo una ruta redirigida se compila y no se ejecuta jamás.
    // Pedirle título sería fijar código muerto; lo que se pide es que no exista.
    const redirigidas = new Set(legacyRedirects().map((r) => r.source));
    expect(redirigidas.has(`/${ruta}`)).toBe(false);
  });
});
