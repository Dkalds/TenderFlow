import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Guardarraíl de ortografía castellana en las cadenas visibles (C7.8).
 *
 * El backlog pedía un barrido: «decenas de cadenas de UI sin tildes
 * (prediccion, analisis, Busqueda, Ultimos)». Medido el 2026-09-07 sobre todo
 * `web/src`: **cero**. La Ola 1 cubrió navegación, filtros, TopNav y `es.json`,
 * y el interior de las páginas se limpió después. El barrido está hecho; lo que
 * faltaba era que siguiera hecho.
 *
 * Qué mira, y qué no
 * ------------------
 * Sólo **prosa**: literales con al menos un espacio. Un identificador
 * (`titulo`, `tecnologia`, `adjudicacion-detectada-titulo`) no es una cadena de
 * interfaz, y exigirle tilde rompería el contrato con la API — que devuelve
 * `titulo`, sin tilde, y así debe seguir. Confundir las dos cosas es lo que
 * hace que este tipo de reglas acaben desactivadas.
 *
 * La lista son palabras que en castellano **siempre** llevan tilde. Quedan
 * fuera a propósito `solo` (la RAE ya no la tilda), `licitaciones`,
 * `sesiones`, `notificaciones` y demás plurales llanos acabados en -s, que son
 * correctos sin tilde y aparecen por todas partes.
 */

const RAIZ = path.resolve(__dirname, "..");

/**
 * Palabras que en prosa castellana no pueden aparecer sin tilde.
 *
 * Cada entrada es la forma **sin** tilde de una palabra que sí la lleva. Ojo con
 * los plurales: `tecnología → tecnologías` y `página → páginas` la conservan y
 * por eso están, pero los acabados en `-ción` la pierden al pluralizar
 * (`predicción → predicciones`, `licitación → licitaciones`), así que su plural
 * NO va en esta lista — incluirlo marca castellano correcto.
 *
 * `predicciones` estuvo aquí hasta 2026-09-08 y no había disparado por
 * casualidad: la primera frase del producto que la usaba bien
 * —«Las predicciones conservan versión y fecha de cálculo», en /metodologia—
 * puso el test en rojo. Un control que marca lo correcto se acaba desactivando.
 */
const SIEMPRE_CON_TILDE = [
  "prediccion",
  "analisis",
  "busqueda",
  "busquedas",
  "ultimo",
  "ultima",
  "ultimos",
  "ultimas",
  "licitacion",
  "adjudicacion",
  "organo",
  "codigo",
  "informacion",
  "configuracion",
  "descripcion",
  "seleccion",
  "sesion",
  "numero",
  "aqui",
  "asi",
  "tecnologia",
  "tecnologias",
  "categoria",
  "pagina",
  "paginas",
  "minimo",
  "maximo",
  "proximo",
  "rapido",
  "facil",
  "dificil",
  "economico",
  "metrica",
  "metricas",
  "grafico",
  "graficos",
  "estadistica",
  "estadisticas",
  "segun",
  "tambien",
  "despues",
  "ademas",
  "aplicacion",
  "actualizacion",
  "exportacion",
  "importacion",
  "organizacion",
] as const;

const EXTENSIONES = new Set([".ts", ".tsx"]);
const EXCLUIDOS = new Set(["__tests__", "generated", "node_modules"]);

/** Literales de cadena y texto JSX. */
const CADENA_RE = /"([^"\n]{5,300})"|'([^'\n]{5,300})'|>([^<>{}\n]{5,300})</g;

function ficheros(dir: string): string[] {
  const salida: string[] = [];
  for (const entrada of readdirSync(dir)) {
    if (EXCLUIDOS.has(entrada)) continue;
    const completo = path.join(dir, entrada);
    if (statSync(completo).isDirectory()) {
      salida.push(...ficheros(completo));
    } else if (EXTENSIONES.has(path.extname(entrada))) {
      salida.push(completo);
    }
  }
  return salida;
}

/** `true` si la cadena parece prosa y no un identificador o una ruta. */
function esProsa(cadena: string): boolean {
  if (!cadena.includes(" ")) return false;
  if (cadena.includes("_") || cadena.includes("http") || cadena.includes("/")) return false;
  // `{`/`}` sobrantes de una interpolación partida por el regex.
  return !cadena.includes("${");
}

describe("ortografía castellana en cadenas visibles", () => {
  const hallazgos: string[] = [];

  for (const fichero of ficheros(RAIZ)) {
    const contenido = readFileSync(fichero, "utf8");
    for (const coincidencia of contenido.matchAll(CADENA_RE)) {
      const cadena = (coincidencia[1] ?? coincidencia[2] ?? coincidencia[3] ?? "").trim();
      if (!esProsa(cadena)) continue;
      for (const palabra of SIEMPRE_CON_TILDE) {
        if (new RegExp(`\\b${palabra}\\b`, "i").test(cadena)) {
          hallazgos.push(`${path.relative(RAIZ, fichero)}: «${cadena.slice(0, 90)}» (${palabra})`);
        }
      }
    }
  }

  it("no queda prosa de interfaz sin tildar", () => {
    expect(hallazgos).toEqual([]);
  });
});
