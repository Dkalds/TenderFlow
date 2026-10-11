/**
 * Tests basados en propiedades (fast-check), con la configuración de la casa.
 *
 * Un test de ejemplo dice «con esta entrada sale esto»; una propiedad dice «con
 * cualquier entrada se cumple esto» y deja que la librería busque la entrada
 * que lo desmiente. Sirve para lo que los ejemplos no alcanzan: ida y vuelta
 * (serializar y volver a leer), idempotencia (normalizar dos veces = una) e
 * invariantes («nunca sale del origen», «siempre suma 100»).
 *
 * Dos decisiones, y las dos son por la suite y no por la librería:
 *
 * 1. **Semilla fija.** Con semilla aleatoria, un fallo en CI puede no repetirse
 *    en el reintento, y un test que a veces falla acaba ignorado. Fija, cada
 *    ejecución prueba exactamente los mismos casos: lo que pasa en local pasa
 *    en CI. El precio es que no explora casos nuevos sola; para eso está
 *    `FC_SEED` (abajo).
 * 2. **Pocas ejecuciones.** La suite completa ya roza los timeouts bajo carga
 *    (un caso cuesta 4–14 veces lo que aislado), así que cada fichero
 *    `*.property.test.ts` tiene que quedarse por debajo de 2 s. 200 casos por
 *    propiedad sobre funciones puras son milisegundos.
 *
 * Para explorar a mano, sin tocar el código:
 *
 *   FC_SEED=azar FC_NUM_RUNS=20000 npm run test -- --expect-min=1 src/lib/__tests__/slug.property.test.ts
 *
 * Cuando una propiedad falla, fast-check imprime la semilla, el `path` y el
 * contraejemplo ya reducido al mínimo. Si lo que destapa es un fallo del
 * código, el contraejemplo se queda en el test como un caso con nombre.
 */
import fc from "fast-check";

/** La fecha en que entraron estos tests; no tiene más significado que ser fija. */
const SEMILLA_FIJA = 20261011;
const EJECUCIONES_POR_DEFECTO = 200;

function semillaDelEntorno(): number {
  const pedida = process.env.FC_SEED;
  if (!pedida) return SEMILLA_FIJA;
  if (pedida === "azar") return Date.now() ^ (Math.random() * 0x1_0000_0000);
  const numero = Number.parseInt(pedida, 10);
  return Number.isFinite(numero) ? numero : SEMILLA_FIJA;
}

function ejecucionesDelEntorno(): number {
  const pedidas = Number.parseInt(process.env.FC_NUM_RUNS ?? "", 10);
  return Number.isFinite(pedidas) && pedidas > 0 ? pedidas : EJECUCIONES_POR_DEFECTO;
}

/**
 * `fc.assert` con la semilla y el número de ejecuciones de la casa.
 *
 * `opciones` gana a los valores por defecto, para la propiedad que necesite
 * menos ejecuciones porque cada caso le sale caro.
 */
export function comprobar<Ts extends [unknown, ...unknown[]]>(
  propiedad: fc.IProperty<Ts>,
  opciones: fc.Parameters<Ts> = {},
): void {
  fc.assert(propiedad, { seed: semillaDelEntorno(), numRuns: ejecucionesDelEntorno(), ...opciones });
}

/** Texto con cualquier Unicode bien formado: acentos, emoji, marcas combinantes. */
export const textoUnicode = (limites: { minLength?: number; maxLength?: number } = {}) =>
  fc.string({ unit: "grapheme", ...limites });
