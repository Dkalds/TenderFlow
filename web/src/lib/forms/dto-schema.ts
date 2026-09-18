/**
 * Esquemas de formulario atados al contrato de OpenAPI (S7.2).
 *
 * Un formulario valida en cliente lo mismo que luego manda al backend, así que
 * sus campos no pueden llamarse como quiera la pantalla: se llaman como el DTO
 * generado en `src/generated/api.d.ts`. `esquemaDeDto` lo hace cumplir en dos
 * sitios a la vez:
 *
 * - **Al compilar.** Una clave que el DTO no tiene es un error de tipos, y
 *   también lo es dejarse una clave del DTO sin decidir: cada una o se valida
 *   en la forma o se declara en `omitidas`. Si el backend añade un campo, el
 *   formulario deja de compilar hasta que alguien decida qué hacer con él.
 * - **Al ejecutar.** El `contrato` que devuelve lleva las claves de la forma y
 *   las omitidas como datos, y `__tests__/contrato-dto.test.ts` las compara con
 *   el texto de `api.d.ts`. Eso cubre lo que los tipos no ven: un `as` de más
 *   o un fichero generado que cambió sin recompilar el formulario.
 *
 * Lo que el esquema valida son los **valores del formulario** (casi siempre
 * cadenas, que es lo que da un `<input>`), no el cuerpo de la petición: la
 * traducción a `number | null` sigue viviendo en cada pantalla. Lo que se
 * comparte con el DTO son las claves, que es justo lo que no se debe duplicar
 * a mano (ADR-014).
 */

import { z } from "zod";
import type { components } from "@/generated/api";

type Schemas = components["schemas"];

/** Nombre de un schema del OpenAPI generado. */
export type NombreDto = keyof Schemas;

/** Claves de texto del DTO `N`. */
export type ClaveDto<N extends NombreDto> = Extract<keyof Schemas[N], string>;

/** Lo que el test de deriva necesita saber de un esquema, como datos. */
export interface ContratoDto {
  dto: NombreDto;
  /** Claves que valida el formulario. */
  claves: readonly string[];
  /** Claves del DTO que el formulario no rellena, a sabiendas. */
  omitidas: readonly string[];
}

/** Forma cuyas claves son todas del DTO `N`. */
type FormaDe<N extends NombreDto, S> = {
  [K in keyof S]: K extends ClaveDto<N> ? z.ZodType : never;
};

/**
 * Error de tipos legible cuando falta decidir alguna clave del DTO: el
 * compilador enseña `{ faltan: "clave" }` en vez de un `never` opaco.
 */
type Exhaustivo<N extends NombreDto, S, O extends readonly string[]> = [
  Exclude<ClaveDto<N>, keyof S | O[number]>,
] extends [never]
  ? unknown
  : { faltan: Exclude<ClaveDto<N>, keyof S | O[number]> };

/**
 * Construye el esquema de un formulario sobre las claves del DTO `dto`.
 *
 * Se usa en dos llamadas para que TypeScript infiera la forma sin tener que
 * repetir el nombre del DTO como parámetro de tipo:
 *
 * ```ts
 * const { esquema, contrato } = esquemaDeDto("OrganizationCreate")({ name: z.string() }, []);
 * ```
 */
export function esquemaDeDto<N extends NombreDto>(dto: N) {
  return <
    S extends Record<string, z.ZodType> & FormaDe<N, S>,
    const O extends readonly Exclude<ClaveDto<N>, keyof S>[],
  >(
    forma: S,
    omitidas: O & Exhaustivo<N, S, O>,
  ) => {
    const contrato: ContratoDto = { dto, claves: Object.keys(forma), omitidas };
    return { esquema: z.object(forma), contrato };
  };
}
