/**
 * Piezas de esquema para los valores que da un `<input>`: siempre cadenas.
 *
 * Cada límite de aquí repite uno que el backend ya aplica (el `Field` de
 * Pydantic citado en cada esquema); validarlo en cliente solo adelanta el
 * mensaje, no inventa una regla nueva.
 */

import { z } from "zod";

/** Número de un campo de texto, aceptando la coma decimal española. */
export function numeroDeTexto(valor: string): number | null {
  const normalizado = valor.trim().replace(",", ".");
  if (!normalizado) return null;
  const numero = Number(normalizado);
  return Number.isFinite(numero) ? numero : null;
}

/** Correo obligatorio (`EmailStr` en el backend). */
export const correo = z
  .string()
  .trim()
  .min(1, "Escribe un correo electrónico.")
  .pipe(z.email("Ese correo no parece válido."));

/** Texto libre opcional con el `max_length` del backend. */
export function textoOpcional(maximo: number) {
  return z.string().max(maximo, `Máximo ${maximo} caracteres.`);
}

/** Importe opcional en euros: vacío o un número no negativo (`ge=0`). */
export const importeOpcional = z.string().refine((valor) => {
  if (!valor.trim()) return true;
  const numero = numeroDeTexto(valor);
  return numero != null && numero >= 0;
}, "Escribe un importe en euros: solo cifras, sin signo negativo.");

/** Entero opcional dentro de `[minimo, maximo]`. */
export function enteroOpcional(minimo: number, maximo: number) {
  return z.string().refine((valor) => {
    if (!valor.trim()) return true;
    const numero = numeroDeTexto(valor);
    return numero != null && Number.isInteger(numero) && numero >= minimo && numero <= maximo;
  }, `Escribe un número entero entre ${minimo} y ${maximo}.`);
}
