/**
 * Las dimensiones del score y sus pesos por defecto.
 *
 * Vive aparte del hook del formulario porque lo leen también las tarjetas, y
 * un módulo entra entero en el bundle de quien use cualquiera de sus exports.
 */

// Debe reflejar `settings.SCORING_WEIGHTS`: es el reparto que el backend
// aplica a quien no tiene perfil, y el que se ofrece al crear uno.
export const DEFAULT_WEIGHTS: Record<string, number> = {
  importe: 20,
  plazo: 15,
  competencia: 20,
  margen: 20,
  afinidad: 15,
  senal_tecnica: 10,
};

/**
 * F1.4 — penalizaciones con peso propio. **No son dimensiones**: no suman en
 * el 100 ni tienen slider, y su valor son los puntos que se restan cuando la
 * oportunidad lleva el flag. Refleja `organo_anula_frecuente` de
 * `settings.SCORING_WEIGHTS`; ponerla a 0 la apaga (`PENALTY_WEIGHT_KEYS` en
 * `shared/scoring_weights.py`).
 */
export const PENALIZACIONES: Record<string, number> = {
  organo_anula_frecuente: 8,
};

export function esPenalizacion(clave: string): boolean {
  return clave in PENALIZACIONES;
}

/** Una sola lista de rótulos para los deslizadores, la propuesta y la barra. */
export const WEIGHT_LABELS: Record<string, string> = {
  importe: "Importe",
  plazo: "Plazo",
  competencia: "Competencia",
  margen: "Margen esperado",
  afinidad: "Afinidad (palabras clave)",
  senal_tecnica: "Señal técnica",
};

/** Suma de las dimensiones; las penalizaciones (F1.4) no cuentan en el 100. */
export function sumWeights(w: Record<string, number>): number {
  return Object.entries(w)
    .filter(([clave]) => !esPenalizacion(clave))
    .reduce((a, [, b]) => a + b, 0);
}

/**
 * Pesos guardados → formulario, completando las dimensiones que falten con 0.
 *
 * Un perfil creado antes de que existiera una dimensión no la trae. Sin este
 * relleno, su slider no aparecería y el usuario no podría activarla nunca; con
 * el 0 explícito la ve, sabe que no está puntuando, y la suma sigue en 100.
 */
export function hydrateWeights(saved: Record<string, number> | null | undefined): Record<string, number> {
  if (!saved) return { ...DEFAULT_WEIGHTS, ...PENALIZACIONES };
  const ceros = Object.fromEntries(Object.keys(DEFAULT_WEIGHTS).map((k) => [k, 0]));
  // Una penalización ausente no se rellena con 0 como las dimensiones: el
  // backend aplica la global a quien no la trae, y rellenarla con 0 la
  // apagaría en silencio al guardar un perfil anterior a F1.4.
  return { ...ceros, ...PENALIZACIONES, ...saved };
}

/** Mismo criterio que valida el backend: división, grupo o código completo. */
export function isValidCpv(value: string): boolean {
  return /^\d{4,8}$/.test(value.trim());
}

/** Separa lo tecleado o pegado en una lista: comas, punto y coma o saltos de línea. */
export function partirLista(texto: string): string[] {
  return texto
    .split(/[\n,;]+/)
    .map((trozo) => trozo.trim())
    .filter(Boolean);
}
