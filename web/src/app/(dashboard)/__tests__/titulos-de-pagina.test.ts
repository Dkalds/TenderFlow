import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

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
 * falla aquí el día que se crea, no cuando alguien la audita.
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
    expect(rutas.length).toBeGreaterThan(20);
  });

  it.each(rutas)("/%s declara metadata.title", (ruta) => {
    expect(declaraTitulo(ruta)).toBe(true);
  });
});
