/**
 * ¿Este valor legal es un relleno de desarrollo en vez de un dato real?
 *
 * Existe porque el guard de `next.config.ts` sólo comprobaba que las variables
 * `NEXT_PUBLIC_LEGAL_*` **no estuvieran vacías**, y una variable definida con un
 * recordatorio dentro pasa esa comprobación igual de bien que una razón social.
 * El resultado se pudo leer en producción: `/aviso-legal` publicaba
 * «Responsable: PLACEHOLDER LOCAL - NO DESPLEGAR, con NIF X0000000X y domicilio
 * … Domicilio de desarrollo, sin validez legal», que es exactamente la página a
 * la que remite la casilla de consentimiento del formulario de acceso.
 *
 * No es un fallo estético: el sitio es indexable y recoge una dirección de
 * correo por consentimiento explícito, así que el RGPD (art. 13) y la LSSI-CE
 * (art. 10) exigen identificar al responsable **en el momento de la recogida**.
 * Un aviso con un placeholder no identifica a nadie.
 *
 * ## Por qué vive en su propio módulo y sin un solo import
 *
 * Lo consumen dos mundos que no comparten resolución de módulos: `next.config.ts`
 * —que carga sus ayudantes por ruta relativa, porque los `paths` de
 * `tsconfig.json` no aplican al cargar la config— y `lib/legal.ts`, que corre en
 * el render. Misma restricción que `lib/space-views.ts`: sin importar nada, el
 * fichero vale en los dos sitios y se puede testear sin arrancar Next.
 *
 * ## Qué se considera relleno
 *
 * Un valor vacío o en blanco, y cualquiera que contenga una de las marcas de
 * abajo. La primera versión comparaba subcadenas sueltas y era **demasiado**
 * generosa: `"desarrollo"` marcaba «Desarrollos Informáticos del Sur, S.A.», y
 * `"todo"` marcaba «Métodos Avanzados, S.L.» y «Avenida Todos los Santos» —dentro
 * de «méTODOs» hay un «todo»—. El coste de ese falso positivo no es teórico: es
 * el build de producción de una empresa con un nombre corriente, roto por su
 * propia razón social.
 *
 * De ahí las dos familias de abajo. Las **frases** se buscan como subcadena
 * porque no aparecen por accidente en un dato societario. Las **palabras** se
 * buscan con frontera de palabra, de modo que casan «todo» pero no «métodos», y
 * «ejemplo» pero no «ejemplar».
 *
 * Sigue inclinado hacia rechazar de más: rechazar cuesta un build fallido con un
 * mensaje que dice qué variable revisar, y no rechazar cuesta publicar un aviso
 * legal inválido durante semanas.
 */

/**
 * Frases que sólo aparecen en un valor puesto para acordarse de cambiarlo. Se
 * buscan como subcadena: ningún dato societario las contiene por casualidad.
 *
 * En minúsculas y sin acentos, porque el predicado normaliza antes de comparar.
 */
const FRASES_DE_RELLENO = [
  "placeholder",
  "no desplegar",
  "sin validez",
  "de desarrollo",
  "por completar",
  "pendiente de",
  "sin definir",
  "a rellenar",
  "cambiar esto",
  // NIF de relleno canónico del repo: nueve caracteres que ninguna AEAT emite.
  "x0000000x",
];

/**
 * Palabras que delatan un relleno **sólo si están sueltas**. Con frontera de
 * palabra: «todo» sí, «métodos» y «todos» no; «ejemplo» sí, «ejemplar» no.
 */
const PALABRAS_DE_RELLENO = ["todo", "tbd", "xxx", "dummy", "ejemplo", "example", "lorem", "pendiente"];

/**
 * ¿Hay que tratar este valor como si la variable no estuviera definida?
 *
 * Devuelve `true` para vacío, blanco y cualquier valor con marca de relleno.
 * Los llamantes lo usan para dos cosas distintas y complementarias: romper el
 * build de producción (`next.config.ts`) y, si aun así llegara a ejecución,
 * resolver la constante a `null` para que la página declare la laguna en vez de
 * imprimir el relleno (`lib/legal.ts`).
 */
export function esValorLegalPlaceholder(valor: string | null | undefined): boolean {
  const limpio = valor?.trim();
  if (!limpio) return true;

  // `normalize` + quitar diacríticos para que «Dirección de desarrollo» case
  // con «desarrollo» aunque el acento no coincida con la marca escrita arriba.
  const normalizado = limpio
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();

  if (FRASES_DE_RELLENO.some((frase) => normalizado.includes(frase))) return true;

  // La frontera de palabra se evalúa sobre el valor ya normalizado —sin
  // acentos—, así que se comporta igual en «ejemplo» que en cualquier palabra
  // ASCII.
  return PALABRAS_DE_RELLENO.some((palabra) => new RegExp(`\\b${palabra}\\b`).test(normalizado));
}
