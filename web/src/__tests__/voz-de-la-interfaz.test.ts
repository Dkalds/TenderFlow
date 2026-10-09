import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import ts from "typescript";
import { beforeAll, describe, expect, it } from "vitest";

/**
 * La voz de la interfaz: tuteo peninsular, y una consola que no narra cómo está
 * hecha. Trinquete de la auditoría anti-vibecode del 2026-09-26
 * (`docs/UX_AUDIT.md`, «Aspecto de plantilla en la consola»).
 *
 * Por qué existe
 * --------------
 * La auditoría encontró dos síntomas de que el texto no tenía dueño:
 *
 * 1. **Tres dialectos mezclados**, a veces en la misma frase: tuteo, voseo y
 *    vosotros («Creá uno… en tus propios sistemas… en vuestras
 *    oportunidades»). Se contaron 15 formas de voseo en cadenas visibles.
 * 2. **La interfaz narraba su arquitectura**: «calculada en backend», «tope del
 *    backend», «sale de otro endpoint», «no se pinta», «corpus completo»
 *    (13 en la consola). Quien usa TenderFlow no sabe qué es un endpoint, y la
 *    honestidad sobre lo estimado o parcial (ADR-014) se dice en su idioma:
 *    «estimación», «parcial: solo las N primeras», «sin datos suficientes».
 *
 * Los dos quedaron a cero el 2026-09-27. Este test impide que vuelvan.
 *
 * Qué mira, y por qué con el AST
 * ------------------------------
 * `scripts/check_ortografia_ui.py` (las tildes) lee con expresiones regulares el
 * texto JSX de **una sola línea** y cinco props de copy en los `.tsx`. Para la
 * voz no alcanza: el voseo vivía también en los toasts de los hooks (`.ts`) y en
 * texto JSX partido en varias líneas, y una regex sobre el fichero entero
 * cuenta los comentarios que citan el texto antiguo para explicar por qué se
 * fue. Aquí se parsea cada fichero con el compilador de TypeScript y se leen
 * solo los nodos que pueden llegar a pantalla: texto JSX, cadenas y trozos de
 * plantilla. Quedan fuera por construcción los comentarios, las rutas de
 * `import`, los tipos literales, las claves de objeto y lo que se pasa a
 * `console.*`, que lee quien desarrolla.
 *
 * Alcance
 * -------
 * - **Voseo y vosotros**: todo `web/src` salvo los tests. No hay ningún sitio
 *   donde sean la voz de la casa.
 * - **Narración de la implementación**: la consola, o sea todo salvo `lib/` y
 *   `app/(publico)/`. En `lib/` vive el contrato de mensajes de error de C2,
 *   que dice a propósito «Error del servidor. Vuelve a intentarlo…», y valores
 *   como el ámbito `"corpus"` de `/ask`, que no se enseñan. En `(publico)`, el
 *   aviso legal y la página de seguridad hablan del servidor porque es el dato
 *   exacto que tienen que dar.
 *
 * Cómo se encoge
 * --------------
 * `EXCEPCIONES` está vacía. Un caso legítimo nuevo se añade con su motivo
 * —se ve en el diff— y el test falla si una excepción deja de hacer falta, para
 * que la lista no se quede con entradas muertas.
 */

const SRC = path.resolve(__dirname, "..");

/**
 * Formas de voseo (y de vosotros) que han salido o pueden salir en la UI. En
 * minúscula; se comparan sin distinguir mayúsculas.
 *
 * El imperativo de vos lleva tilde en la última sílaba («guardá») y la pierde
 * con un pronombre detrás («guardalo»), así que van las dos series. «animate»
 * no está a propósito: es también la clase `animate-*` de Tailwind. La lista va
 * en párrafo (`prettier-ignore`): a una palabra por línea ocuparía 150.
 */
// prettier-ignore
const VOSEO = [
  // Imperativo, verbos en -ar.
  "usá", "probá", "cerrá", "guardá", "creá", "revisá", "mirá", "esperá", "cambiá", "borrá",
  "eliminá", "seleccioná", "completá", "confirmá", "intentá", "reintentá", "contactá",
  "configurá", "activá", "desactivá", "descargá", "editá", "actualizá", "recargá", "avisá",
  "iniciá", "cancelá", "aceptá", "continuá", "copiá", "pegá", "filtrá", "ordená", "exportá",
  "importá", "invitá", "asigná", "marcá", "desmarcá", "arrastrá", "soltá", "tocá", "pulsá",
  "presioná", "ingresá", "agregá", "buscá", "entrá", "andá", "empezá", "comenzá", "dejá",
  "llevá", "pasá", "quitá", "sacá", "mandá", "enviá", "compará", "ajustá", "anotá", "apuntá",
  "registrá", "vinculá", "conectá", "desconectá", "programá", "comprobá", "verificá",
  "aplicá", "indicá",
  // Imperativo, verbos en -er e -ir.
  "volvé", "hacé", "poné", "tené", "leé", "escogé", "mové", "resolvé", "devolvé", "escribí",
  "abrí", "subí", "pedí", "decí", "añadí", "compartí", "salí", "definí", "elegí", "seguí",
  "repetí", "permití", "incluí", "excluí", "descubrí", "recibí", "preferí", "decidí",
  // Imperativo con pronombre.
  "fijate", "asegurate", "acordate", "olvidate", "quedate", "suscribite",
  "contanos", "decinos", "escribinos", "avisanos", "mandanos", "contame", "decime", "avisame",
  "escribime", "probalo", "guardalo", "revisalo", "miralo", "hacelo", "ponelo", "decilo",
  "pasalo", "dejalo", "borralo", "eliminalo", "cambialo",
  // Presente de vos.
  "podés", "tenés", "querés", "sabés", "perdés", "hacés", "ponés", "debés", "necesitás",
  "usás", "buscás", "encontrás", "empezás", "guardás", "elegís", "escribís", "decís", "venís",
  "pedís", "seguís", "preferís", "recibís",
  // Vosotros: «las oportunidades de tu equipo», no «vuestras oportunidades».
  "vosotros", "vosotras", "vuestro", "vuestra", "vuestros", "vuestras",
];

/**
 * Palabras de quien construye la consola, no de quien la usa. `API` no está:
 * en Ajustes › Claves de API y en Ops › Estado la API es el producto.
 */
const NARRACION = [
  "backends?",
  "frontends?",
  "endpoints?",
  "servidor(?:es)?",
  "corpus",
  "fixtures?",
  "payloads?",
  "snake_case",
  "se\\s+pintan?",
  "pintamos",
  "denominador(?:es)?",
  "renderiza\\p{L}*",
  "hardcode\\p{L}*",
];

/**
 * Frontera de palabra que no parte identificadores: `data-testid="endpoint-url"`
 * o la clave de consulta `"api-keys"` no son texto, y `\b` de JavaScript no
 * reconoce las letras con tilde como parte de una palabra.
 */
const palabra = (alternativas: string[]) =>
  new RegExp(`(?<![\\p{L}\\p{N}_-])(?:${alternativas.join("|")})(?![\\p{L}\\p{N}_-])`, "giu");

const RE_VOSEO = palabra(VOSEO);
const RE_NARRACION = palabra(NARRACION);

/** La consola: todo salvo `lib/` y la superficie pública (ver el alcance arriba). */
const esConsola = (rel: string) => !rel.startsWith("lib/") && !rel.startsWith("app/(publico)/");

/**
 * Casos legítimos, por fichero relativo a `src/` → término exacto → motivo.
 * **Solo puede encoger.** Vacía desde el día que se escribió.
 */
const EXCEPCIONES: Record<string, Record<string, string>> = {};

interface Texto {
  texto: string;
  /** Línea (1-based) del carácter `indice` de `texto`: el texto JSX ocupa varias. */
  linea: (indice: number) => number;
}

interface Hallazgo {
  fichero: string;
  linea: number;
  termino: string;
  texto: string;
}

/** Nodos que pueden llegar a pantalla. */
function textosVisibles(fuente: string, nombre = "fuente.tsx"): Texto[] {
  const sf = ts.createSourceFile(
    nombre,
    fuente,
    ts.ScriptTarget.Latest,
    false,
    nombre.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const textos: Texto[] = [];
  // `inicio`: dónde empieza `texto` en la fuente. El texto JSX empieza justo
  // tras el `>` (su `pos`); una cadena o un trozo de plantilla, un carácter
  // después de su comilla, acento grave o `}`. Un escape (`\n`) desplaza la
  // cuenta dentro de su cadena, pero no la cambia de línea.
  const anotar = (texto: string, inicio: number) => {
    textos.push({ texto, linea: (i) => sf.getLineAndCharacterOfPosition(inicio + i).line + 1 });
  };

  const esConsoleOImport = (nodo: ts.CallExpression) => {
    const callee = nodo.expression;
    if (callee.kind === ts.SyntaxKind.ImportKeyword) return true;
    if (ts.isIdentifier(callee) && callee.text === "require") return true;
    return (
      ts.isPropertyAccessExpression(callee) &&
      ts.isIdentifier(callee.expression) &&
      callee.expression.text === "console"
    );
  };

  const visitar = (nodo: ts.Node): void => {
    // Rutas de módulo, tipos y lo que solo lee quien desarrolla.
    if (ts.isImportDeclaration(nodo) || ts.isExportDeclaration(nodo) || ts.isTypeNode(nodo)) return;
    if (ts.isCallExpression(nodo) && esConsoleOImport(nodo)) return;
    // Las claves de un objeto o de un enum no se leen; su valor, sí.
    if (ts.isPropertyAssignment(nodo) || ts.isEnumMember(nodo)) {
      if (nodo.initializer) visitar(nodo.initializer);
      return;
    }

    if (ts.isJsxText(nodo)) {
      if (nodo.text.trim()) anotar(nodo.text, nodo.pos);
    } else if (
      ts.isStringLiteral(nodo) ||
      ts.isNoSubstitutionTemplateLiteral(nodo) ||
      ts.isTemplateHead(nodo) ||
      ts.isTemplateMiddle(nodo) ||
      ts.isTemplateTail(nodo)
    ) {
      anotar(nodo.text, nodo.getStart(sf) + 1);
    }
    // Sin `return` en el callback: `forEachChild` deja de recorrer en cuanto uno
    // devuelve algo verdadero, y el recuento saldría corto sin avisar.
    ts.forEachChild(nodo, (hijo) => {
      visitar(hijo);
    });
  };

  visitar(sf);
  return textos;
}

function buscar(textos: Texto[], re: RegExp, fichero: string): Hallazgo[] {
  const hallazgos: Hallazgo[] = [];
  for (const { linea, texto } of textos) {
    for (const m of texto.matchAll(re)) {
      hallazgos.push({
        fichero,
        linea: linea(m.index ?? 0),
        termino: m[0].toLowerCase().replace(/\s+/g, " "),
        texto: texto.trim().replace(/\s+/g, " ").slice(0, 90),
      });
    }
  }
  return hallazgos;
}

function ficherosFuente(dir = SRC): string[] {
  const salida: string[] = [];
  for (const entrada of readdirSync(dir, { withFileTypes: true })) {
    const ruta = path.join(dir, entrada.name);
    if (entrada.isDirectory()) {
      if (entrada.name === "__tests__" || entrada.name === "generated") continue;
      salida.push(...ficherosFuente(ruta));
    } else if (
      /\.tsx?$/.test(entrada.name) &&
      !/\.(test|spec)\.tsx?$/.test(entrada.name) &&
      !entrada.name.endsWith(".d.ts")
    ) {
      salida.push(ruta);
    }
  }
  return salida;
}

const formato = (hs: Hallazgo[]) =>
  hs.map((h) => `  src/${h.fichero}:${h.linea} «${h.termino}» — ${h.texto}`).join("\n");

const exceptuado = (h: Hallazgo) => Boolean(EXCEPCIONES[h.fichero]?.[h.termino]);

describe("controles del propio escáner (un trinquete que no ve nada pasa siempre)", () => {
  const MUESTRA = [
    'import { x } from "@/components/prefetch-servidor";',
    "// Antes decía «Guardá los cambios» y «calculado en backend».",
    'type Origen = "backend" | "frontend";',
    'const claves = { endpoint: "/api/v1/x", "servidor": 1 };',
    'console.warn("sin respuesta del backend");',
    'const lazy = () => import("./endpoint-panel");',
    'const testId = "endpoint-url";',
    'toast.error("Probá de nuevo en unos segundos");',
    "const aviso = `Guardalo ${n} veces`;",
    "export function Vista() {",
    "  return (",
    '    <p title="Dato calculado en backend">',
    "      Revisá las",
    "      oportunidades de vuestro equipo; el total no se pinta.",
    "    </p>",
    "  );",
    "}",
  ].join("\n");

  it("encuentra el voseo en toasts, plantillas y texto JSX de varias líneas", () => {
    const hs = buscar(textosVisibles(MUESTRA), RE_VOSEO, "muestra.tsx");
    expect(hs.map((h) => [h.linea, h.termino])).toEqual([
      [8, "probá"],
      [9, "guardalo"],
      [13, "revisá"],
      [14, "vuestro"],
    ]);
  });

  it("encuentra la narración en props y texto JSX, y no en comentarios, imports, tipos, claves ni console", () => {
    const hs = buscar(textosVisibles(MUESTRA), RE_NARRACION, "muestra.tsx");
    expect(hs.map((h) => [h.linea, h.termino])).toEqual([
      [12, "backend"],
      [14, "se pinta"],
    ]);
  });
});

describe("voz de la interfaz en web/src", () => {
  let voseo: Hallazgo[] = [];
  let narracion: Hallazgo[] = [];
  let ficheros = 0;

  beforeAll(() => {
    for (const ruta of ficherosFuente()) {
      const rel = path.relative(SRC, ruta).split(path.sep).join("/");
      const textos = textosVisibles(readFileSync(ruta, "utf8"), rel);
      voseo.push(...buscar(textos, RE_VOSEO, rel));
      if (esConsola(rel)) narracion.push(...buscar(textos, RE_NARRACION, rel));
      ficheros += 1;
    }
    voseo = voseo.filter((h) => !exceptuado(h));
    narracion = narracion.filter((h) => !exceptuado(h));
  }, 60_000);

  it("recorre el árbol de verdad (si no encuentra ficheros, los otros casos no dicen nada)", () => {
    expect(ficheros).toBeGreaterThan(400);
  });

  it("habla de tú: ni voseo ni vosotros", () => {
    expect(
      voseo,
      `Voseo o vosotros en texto visible (la casa tutea: «Guarda», «Revisa», «tu equipo»):\n${formato(voseo)}`,
    ).toEqual([]);
  });

  it("la consola no narra su implementación", () => {
    expect(
      narracion,
      "La consola nombra su implementación. Dilo en lenguaje de usuario: «estimación», " +
        "«parcial: solo las N primeras», «sin datos suficientes», «no se muestra»…\n" +
        formato(narracion),
    ).toEqual([]);
  });

  it("cada excepción sigue haciendo falta (la lista solo encoge)", () => {
    const muertas: string[] = [];
    for (const [fichero, terminos] of Object.entries(EXCEPCIONES)) {
      let fuente = "";
      try {
        fuente = readFileSync(path.join(SRC, fichero), "utf8");
      } catch {
        muertas.push(`${fichero} (ya no existe)`);
        continue;
      }
      const textos = textosVisibles(fuente, fichero);
      const vivos = new Set(
        [...buscar(textos, RE_VOSEO, fichero), ...buscar(textos, RE_NARRACION, fichero)].map((h) => h.termino),
      );
      for (const termino of Object.keys(terminos)) {
        if (!vivos.has(termino)) muertas.push(`${fichero} «${termino}»`);
      }
    }
    expect(muertas, "Quita estas excepciones de EXCEPCIONES: ya no hacen falta").toEqual([]);
  });
});
