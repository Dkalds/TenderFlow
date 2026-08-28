/**
 * Punto único de reporte de errores de cliente.
 *
 * Hasta ahora esto era un `console.error` con nombre bonito: en producción un
 * error de JavaScript solo se descubría si un usuario lo contaba. No hay Sentry
 * (`grep -ri sentry web/` = 0 resultados) y añadirlo es un cambio de
 * dependencias que requiere OK humano, así que el canal se construye con lo que
 * ya hay: un POST al endpoint propio `POST /api/v1/security/client-error`, que
 * solo escribe en el log estructurado del backend.
 *
 * **La CSP lo permite y conviene dejarlo dicho**, porque si no encajara el
 * reporte se bloquearía en silencio y el colector de errores sería, él mismo, un
 * error invisible. Las dos ramas de `buildCsp` (`web/src/proxy.ts`) —la de la
 * superficie prerenderizada y la del dashboard con nonce— declaran
 * `connect-src 'self'`, y el destino es una ruta **relativa**: el navegador la
 * resuelve contra el origen de la página, que es el de Next. La API vive en
 * otro origen (Vercel ↔ Render), pero el salto lo da el `rewrites()` de
 * `next.config.ts` en el servidor, no el navegador, así que desde el punto de
 * vista de la CSP esto es `'self'` y `sendBeacon` —que también está gobernado
 * por `connect-src`— pasa. Mover el destino a un dominio ajeno obligaría a
 * tocar `connect-src` en el mismo commit.
 *
 * **Qué viaja al servidor**: mensaje, origen, etiqueta de contexto, `pathname`
 * (sin query), stack y `digest` de Next.
 * **Qué NO viaja**: el `extra` de los call-sites. Es el parámetro por el que
 * hoy pasan objetos arbitrarios de dominio y mañana pasaría un email o el
 * contenido de un formulario; se queda en la consola local y no cruza la red.
 * Tampoco viaja la query string (`location.search`), por lo mismo: el ámbito de
 * una pantalla vive ahí y puede llevar nombres de empresa o identificadores.
 */

/** De dónde salió el reporte. Es una dimensión del log, no texto libre. */
export type OrigenError = "manual" | "onerror" | "unhandledrejection" | "global-error";

const ENDPOINT = "/api/v1/security/client-error";

/**
 * Presupuesto de envíos en ventana deslizante. Un bucle de render que lanza en
 * cada frame genera miles de errores: sin tope, el reporter deja de ser el
 * diagnóstico y pasa a ser la caída. La deduplicación de abajo corta el caso
 * habitual (el mismo error repetido); esto cubre el que no cubre — cada vuelta
 * produce un mensaje distinto porque lleva un índice o un timestamp dentro, así
 * que la huella nunca se repite.
 *
 * Deslizante y no "por carga de página" a propósito: esto es una SPA y una
 * sesión dura horas. Un contador que no se rellena dejaría el reporter mudo el
 * resto de la tarde por una ráfaga de los primeros diez segundos.
 */
const MAX_REPORTES_POR_VENTANA = 8;
const VENTANA_ENVIOS_MS = 60_000;

/** Dos apariciones del mismo error dentro de esta ventana cuentan como una. */
const VENTANA_DEDUPE_MS = 5 * 60_000;

// Recorte en cliente. El servidor vuelve a truncar por su cuenta —no se fía del
// emisor, y hace bien—, pero recortar aquí evita mandar un stack de 40 KB que
// el endpoint rechazaría entero por tamaño, perdiendo también el mensaje.
const MAX_MENSAJE = 300;
const MAX_STACK = 2000;
const MAX_CONTEXTO = 80;

/**
 * Huella del error → instante del último envío.
 *
 * No necesita tope de tamaño: cada llamada purga lo caducado, así que el mapa
 * queda acotado por lo que quepa enviar dentro de la ventana de deduplicación
 * (8 por minuto × 5 minutos = 40 entradas como mucho).
 */
const huellas = new Map<string, number>();

/** Instantes de los últimos envíos, para la ventana deslizante. */
let enviosRecientes: number[] = [];

/**
 * Reinicia el estado de deduplicación y el presupuesto de envíos.
 *
 * Existe **para los tests**: el módulo guarda estado a nivel de módulo y sin
 * esto un caso contaminaría al siguiente. En producción no se llama nunca.
 */
export function reiniciarReporteErrores(): void {
  huellas.clear();
  enviosRecientes = [];
}

function mensajeDe(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return "Unknown error";
}

/** El `digest` que Next adjunta a los errores de servidor, si lo hay. */
function digestDe(error: unknown): string {
  if (typeof error !== "object" || error === null) return "";
  const valor = (error as { digest?: unknown }).digest;
  return typeof valor === "string" ? valor : "";
}

/**
 * ¿Toca enviar este error, o ya lo vimos / ya gastamos el presupuesto?
 *
 * Purga las huellas caducadas de paso: es el único momento en que se recorre el
 * mapa, y así no hace falta un temporizador que mantener vivo.
 */
function debeEnviar(huella: string, ahora: number): boolean {
  for (const [clave, visto] of huellas) {
    if (ahora - visto > VENTANA_DEDUPE_MS) huellas.delete(clave);
  }
  if (huellas.has(huella)) return false;

  enviosRecientes = enviosRecientes.filter((t) => ahora - t <= VENTANA_ENVIOS_MS);
  if (enviosRecientes.length >= MAX_REPORTES_POR_VENTANA) return false;

  huellas.set(huella, ahora);
  enviosRecientes.push(ahora);
  return true;
}

/**
 * Envía el reporte. `sendBeacon` primero porque sobrevive a la navegación —un
 * error que se produce justo antes de cambiar de página es justo el que se
 * pierde con `fetch` normal—, y es lo que ya hace el `track` de analytics.
 *
 * `fetch` es el respaldo para navegadores sin `sendBeacon` y para cuando la cola
 * del beacon está llena (devuelve `false`): `keepalive: true` le da la misma
 * garantía de supervivencia, y `credentials: "omit"` evita mandar la cookie de
 * sesión a un endpoint que no la necesita ni la mira.
 */
function enviar(cuerpo: string): void {
  try {
    if (typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function") {
      const blob = new Blob([cuerpo], { type: "application/json" });
      if (navigator.sendBeacon(ENDPOINT, blob)) return;
    }
  } catch {
    // sendBeacon puede lanzar (cuota, tipo de blob rechazado). Se cae al fetch.
  }
  try {
    void fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: cuerpo,
      keepalive: true,
      credentials: "omit",
    }).catch(() => {
      // Sin red, 429 o 413: el reporte se pierde y no pasa nada. Lo que no
      // puede pasar es que quede una promesa rechazada sin manejar, porque eso
      // dispara `unhandledrejection` y el listener volvería a llamar aquí.
    });
  } catch {
    // `fetch` inexistente (entorno no-navegador). Silencio.
  }
}

/**
 * Reporta un error.
 *
 * **Nunca lanza, bajo ninguna circunstancia.** Un reporter que revienta dentro
 * del manejador de errores rompe la página que venía a diagnosticar y, peor,
 * puede realimentarse con su propio fallo. De ahí el `try/catch` que envuelve
 * todo el cuerpo, incluido el `console.error`.
 *
 * @param context Etiqueta del call-site ("ConsoleRail.logout"). Se loguea.
 * @param error El error. Se usan `message`, `stack` y `digest`.
 * @param extra Contexto de depuración. **Solo consola local, nunca se envía.**
 * @param origen Qué disparó el reporte. Dimensión del log.
 */
export function reportError(
  context: string,
  error: unknown,
  extra?: Record<string, unknown>,
  origen: OrigenError = "manual",
): void {
  try {
    const message = mensajeDe(error);

    if (process.env.NODE_ENV === "development") {
      console.error(`[${context}]`, message, extra ?? "");
    }

    if (error instanceof Error && error.stack) {
      console.debug(error.stack);
    }

    // En vitest no se hace red: los tests que sí ejercitan el envío stubean
    // `NODE_ENV`. En el bundle del navegador esta comparación es constante
    // (`"production" === "test"`) y el bloque entero desaparece del build.
    if (process.env.NODE_ENV === "test") return;
    if (typeof window === "undefined") return;

    if (!debeEnviar(`${origen}|${context}|${message}`, Date.now())) return;

    enviar(
      JSON.stringify({
        message: message.slice(0, MAX_MENSAJE),
        source: origen,
        context: context.slice(0, MAX_CONTEXTO),
        // Solo el `pathname`: `location.search` se queda fuera a propósito.
        path: window.location?.pathname ?? "",
        stack: error instanceof Error && error.stack ? error.stack.slice(0, MAX_STACK) : "",
        digest: digestDe(error),
      }),
    );
  } catch {
    // Innegociable: el reporter no puede ser la causa de un error.
  }
}
