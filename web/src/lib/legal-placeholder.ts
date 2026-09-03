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
 * abajo. Es deliberadamente **generoso en falsos positivos**: rechazar de más
 * cuesta un build fallido con un mensaje que dice qué variable revisar; rechazar
 * de menos cuesta publicar un aviso legal inválido durante semanas. Una razón
 * social real no contiene «placeholder» ni «no desplegar».
 */

/**
 * Marcas que delatan un valor de relleno. En minúsculas y sin acentos: el
 * predicado normaliza antes de comparar, así que «Pendiente» y «pendiente»
 * casan igual.
 */
const MARCAS_DE_RELLENO = [
  "placeholder",
  "no desplegar",
  "sin validez",
  "desarrollo",
  "pendiente",
  "por completar",
  "completar",
  "ejemplo",
  "example",
  "dummy",
  "tbd",
  "todo",
  "xxx",
  // NIF de relleno canónico del repo: nueve caracteres que ninguna AEAT emite.
  "x0000000x",
];

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

  return MARCAS_DE_RELLENO.some((marca) => normalizado.includes(marca));
}
