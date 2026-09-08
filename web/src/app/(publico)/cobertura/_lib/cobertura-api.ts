import { PHASE_PRODUCTION_BUILD } from "next/constants";
import type { Schemas } from "@/lib/api-types";

/**
 * La cobertura declarada, leída de `GET /api/v1/publico/cobertura`.
 *
 * ## Por qué esta página tiene que preguntar
 *
 * Hasta T7, `/cobertura` nombraba PLACSP, TED, Galicia y Euskadi en un párrafo
 * escrito a mano. Había siete fuentes registradas. Nada fallaba: una página de
 * prosa no se entera de que el código cambió, y el visitante tampoco. Ahora la
 * lista y sus estados salen de `scraper/connectors/REGISTERED_SOURCES`, que es
 * el mismo inventario que el healthcheck usa para alertar — o sea, la única
 * copia que no puede quedarse atrás sin que alguien se dé cuenta.
 *
 * ## Los tipos
 *
 * Salen del esquema generado, no de una copia a mano: una interfaz escrita
 * aquí deja de coincidir con el backend en silencio, que es exactamente el
 * defecto que esta página vino a corregir en la prosa.
 *
 * ## Ausencia contra "no pude preguntar"
 *
 * Misma regla que `lib/publico-api.ts`, y por el mismo motivo: la página es ISR
 * (`revalidate = 3600`), así que una regeneración que pilla la API caída puede
 * **sustituir en caché la copia buena**. De ahí que un fallo lance en vez de
 * devolver una lista vacía: Next falla la regeneración, conserva la copia
 * anterior y lo vuelve a intentar. Una tabla de fuentes vacía sería, además, la
 * peor mentira posible en esta página concreta.
 *
 * No se reintenta dentro de la llamada. El reintento de `publico-api` cubre el
 * 502 mientras rota una instancia; aquí el desenlace de ese caso ya es el
 * correcto —conservar lo publicado— y añadir latencia al render no lo mejora.
 *
 * La excepción es la misma: el job `frontend` de CI compila **sin
 * `API_BASE_URL` a propósito**, y ahí no hay copia stale que proteger. Solo en
 * ese caso se degrada a `null`, y el componente se calla en vez de inventar.
 */

export type FuenteCobertura = Schemas["FuenteCobertura"];
export type AmbitoFueraDeAlcance = Schemas["AmbitoFueraDeAlcance"];
export type Cobertura = Schemas["Cobertura"];

/** `activa | opcional | fuera_de_alcance`, tal como lo declara el esquema. */
export type EstadoCobertura = FuenteCobertura["estado"];

const REVALIDAR_SEGUNDOS = 3600;

function origenApi(): string {
  // fdi-allow:localhost-url — fallback de desarrollo para fetch SSR; no es dato renderizado.
  return process.env.API_BASE_URL ?? "http://localhost:8080";
}

function buildSinBackend(): boolean {
  return process.env.NEXT_PHASE === PHASE_PRODUCTION_BUILD && !process.env.API_BASE_URL;
}

/**
 * `null` significa **solo** "se compiló sin backend al que preguntar".
 * Cualquier otro fallo lanza; ver el docstring del módulo.
 */
export async function obtenerCobertura(): Promise<Cobertura | null> {
  const url = `${origenApi()}/api/v1/publico/cobertura`;

  try {
    const respuesta = await fetch(url, {
      next: { revalidate: REVALIDAR_SEGUNDOS },
      headers: { Accept: "application/json" },
    });
    if (!respuesta.ok) {
      throw new Error(`La API pública respondió ${respuesta.status} a /cobertura`);
    }
    return (await respuesta.json()) as Cobertura;
  } catch (causa) {
    if (buildSinBackend()) {
      console.warn(
        "[cobertura] no se pudo leer la cobertura declarada. Build sin API_BASE_URL: " +
          "la página se publica sin la tabla de fuentes y la primera revalidación la rellena.",
        causa,
      );
      return null;
    }
    throw causa;
  }
}
