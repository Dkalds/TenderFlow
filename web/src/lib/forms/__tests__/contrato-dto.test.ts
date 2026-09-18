import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import * as z from "zod/mini";
import { esquemaDeDto } from "../dto-schema";
import { CONTRATOS_DE_FORMULARIO } from "../esquemas";

/**
 * Deriva entre los esquemas de formulario y el OpenAPI generado (S7.2).
 *
 * Se lee `src/generated/api.d.ts` como texto, no se importan sus tipos: lo
 * que se quiere comprobar es el fichero que de verdad está en el repo (el que
 * `make check-api-contract` mantiene al día con el backend), y un tipo no
 * existe en tiempo de ejecución. Si el backend añade, quita o renombra un
 * campo de uno de estos DTO, este test lo dice aunque nadie haya recompilado
 * el formulario.
 */

const API_DTS = readFileSync(path.resolve(__dirname, "../../../generated/api.d.ts"), "utf8");

interface ClavesDto {
  todas: string[];
  obligatorias: string[];
}

/** Claves de primer nivel de `components["schemas"][nombre]`. */
function clavesDelDto(nombre: string): ClavesDto {
  const lineas = API_DTS.split(/\r?\n/);
  const inicio = lineas.indexOf(`        ${nombre}: {`);
  if (inicio < 0) throw new Error(`El DTO ${nombre} no está en api.d.ts`);
  const todas: string[] = [];
  const obligatorias: string[] = [];
  for (const linea of lineas.slice(inicio + 1)) {
    if (/^ {8}\}/.test(linea)) break;
    // Doce espacios: primer nivel. Los objetos anidados (`weights`) van más
    // adentro y sus claves no son del DTO.
    const campo = /^ {12}"?([\w-]+)"?(\?)?:/.exec(linea);
    if (!campo) continue;
    todas.push(campo[1]);
    if (!campo[2]) obligatorias.push(campo[1]);
  }
  return { todas, obligatorias };
}

describe("esquemas de formulario frente al DTO generado", () => {
  it("el lector de api.d.ts encuentra claves y distingue las obligatorias", () => {
    expect(clavesDelDto("LoginRequest")).toEqual({
      todas: ["email", "password", "remember"],
      obligatorias: ["email", "password", "remember"],
    });
    // `weights` es un objeto anidado: sus claves no deben colarse.
    expect(clavesDelDto("UserProfileBody").todas).not.toContain("key");
    expect(() => clavesDelDto("NoExiste")).toThrow(/NoExiste/);
  });

  for (const [formulario, contrato] of Object.entries(CONTRATOS_DE_FORMULARIO)) {
    describe(`${formulario} (${contrato.dto})`, () => {
      const dto = clavesDelDto(contrato.dto);

      it("solo valida claves que el DTO tiene", () => {
        expect(contrato.claves.filter((clave) => !dto.todas.includes(clave))).toEqual([]);
      });

      it("cada clave del DTO está validada u omitida a sabiendas, y solo una de las dos", () => {
        const decididas = [...contrato.claves, ...contrato.omitidas].sort();
        expect(decididas).toEqual([...dto.todas].sort());
      });

      it("no omite ninguna clave obligatoria sin default", () => {
        // Una obligatoria omitida solo es válida si el backend le pone default
        // (`remember`, `active`, `visibility`…); openapi-typescript las marca
        // obligatorias igual, así que se exige la anotación `@default`.
        const sinDefault = contrato.omitidas.filter(
          (clave) => dto.obligatorias.includes(clave) && !tieneDefault(contrato.dto, clave),
        );
        expect(sinDefault).toEqual([]);
      });
    });
  }
});

/** ¿El comentario JSDoc del campo lleva `@default`? */
function tieneDefault(nombre: string, clave: string): boolean {
  const lineas = API_DTS.split(/\r?\n/);
  const inicio = lineas.indexOf(`        ${nombre}: {`);
  const bloque: string[] = [];
  for (const linea of lineas.slice(inicio + 1)) {
    if (/^ {8}\}/.test(linea)) break;
    if (new RegExp(`^ {12}"?${clave}"?\\??:`).test(linea)) {
      return bloque.some((l) => l.includes("@default"));
    }
    // Cada campo o comentario nuevo de primer nivel empieza un bloque limpio.
    if (/^ {12}(\/\*\*|"?[\w-]+"?\??:)/.test(linea)) bloque.length = 0;
    bloque.push(linea);
  }
  return false;
}

describe("esquemaDeDto", () => {
  it("devuelve el contrato como datos junto al esquema", () => {
    const { esquema, contrato } = esquemaDeDto("OrganizationCreate")({ name: z.string() }, []);
    expect(contrato).toEqual({ dto: "OrganizationCreate", claves: ["name"], omitidas: [] });
    expect(esquema.parse({ name: "x", sobra: 1 })).toEqual({ name: "x" });
  });

  it("rechaza al compilar claves ajenas, claves sin decidir y omitidas duplicadas", () => {
    // Las tres líneas solo compilan porque el error que esperan existe:
    // `tsc --noEmit` (make web-typecheck) falla si alguna deja de darlo.
    // @ts-expect-error `nope` no es de OrganizationCreate
    esquemaDeDto("OrganizationCreate")({ name: z.string(), nope: z.string() }, []);
    // @ts-expect-error falta decidir `remember`
    esquemaDeDto("LoginRequest")({ email: z.string(), password: z.string() }, []);
    // @ts-expect-error `name` ya está en la forma
    esquemaDeDto("OrganizationCreate")({ name: z.string() }, ["name"]);
  });
});
