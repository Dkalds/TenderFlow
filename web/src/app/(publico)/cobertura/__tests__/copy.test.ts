import { describe, expect, it } from "vitest";
import { esValorLegalPlaceholder } from "@/lib/legal-placeholder";
import * as copy from "../_lib/copy";

/**
 * El copy de `/cobertura` no puede ser un recordatorio.
 *
 * Es el criterio de aceptación de T7, y no es una formalidad: esta página es
 * indexable y es la que declara el universo del que salen todas las cifras del
 * producto. Un «por completar» publicado aquí no rompe nada —el build pasa, la
 * página responde 200— y desmiente exactamente lo que la página existe para
 * afirmar. El precedente está en el módulo del predicado: `/aviso-legal`
 * estuvo publicando «PLACEHOLDER LOCAL - NO DESPLEGAR» en producción.
 *
 * Se recorre el módulo entero por reflexión, y no una lista de constantes: una
 * frase nueva entra en el test por existir, sin que nadie se acuerde de
 * añadirla. `esValorLegalPlaceholder` marca además lo vacío y lo que solo son
 * espacios, así que esto es también el guard de «ningún rótulo en blanco».
 *
 * Lo que este test NO cubre, y conviene tener presente: la otra mitad del texto
 * de la página —nombres de fuente, alcances, exclusiones— llega por la API y
 * nunca pasa por aquí. Su equivalente vive en `tests/test_t7_cobertura.py`.
 */

function cadenas(valor: unknown, ruta: string): [string, string][] {
  if (typeof valor === "string") return [[ruta, valor]];
  if (Array.isArray(valor)) return valor.flatMap((v, i) => cadenas(v, `${ruta}[${i}]`));
  if (valor && typeof valor === "object") {
    return Object.entries(valor).flatMap(([k, v]) => cadenas(v, `${ruta}.${k}`));
  }
  return [];
}

const TEXTOS = cadenas(copy, "copy");

describe("el copy de /cobertura", () => {
  it("encuentra texto que revisar", () => {
    // Sin esto, un `export` renombrado dejaría el `it.each` vacío y la suite
    // pasaría sin haber mirado una sola frase.
    expect(TEXTOS.length).toBeGreaterThanOrEqual(20);
  });

  it.each(TEXTOS)("%s no es un relleno de desarrollo", (_ruta, texto) => {
    expect(esValorLegalPlaceholder(texto)).toBe(false);
  });

  it("no publica ninguna cifra de cuota ni porcentaje", () => {
    // Regla dura de `docs/regional-source-coverage.md`: los feeds regionales
    // son cobertura de descubrimiento y no se suman como censo. El texto sí
    // puede (y debe) explicar por qué no hay ninguna.
    for (const [ruta, texto] of TEXTOS) {
      expect(texto, ruta).not.toMatch(/\d+([.,]\d+)?\s*%/);
    }
  });

  it("declara explícitamente que no hay cuota de mercado", () => {
    expect(copy.FUENTES.sinCuota.toLowerCase()).toContain("cuota de mercado");
  });
});
