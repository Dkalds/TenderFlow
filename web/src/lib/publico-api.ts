import { PHASE_PRODUCTION_BUILD } from "next/constants";
import type { components } from "@/generated/api";

/**
 * Acceso a `/api/v1/publico` desde Server Components.
 *
 * No usa el cliente tipado de `api-client.ts` a propósito. Aquél está pensado
 * para el navegador: envía cookies (`credentials: "include"`) y redirige a
 * `/login` ante un 401. Aquí no hay ni cookie ni navegador — y sobre todo, una
 * redirección a login sería exactamente lo contrario de lo que debe pasar en
 * una página pública.
 *
 * Los tipos sí salen del esquema generado, así que un cambio en el contrato de
 * la API rompe el build en vez de romper la página en producción.
 *
 * ## Por qué "no hay dato" y "no pude saberlo" no pueden ser el mismo valor
 *
 * Hasta 2026-08 `pedir` devolvía `null` en tres situaciones que no tienen nada
 * que ver entre sí: error de transporte, respuesta no-ok de cualquier código, y
 * 404 legítimo. Los llamantes leían ese `null` como "no existe" y hacían
 * `notFound()` o publicaban una lista vacía.
 *
 * Con ISR (`revalidate = 3600`) esa confusión no degrada: **destruye**. Una
 * revalidación que pilla la API caída regenera la página como 404 y esa 404
 * *sustituye en caché la copia buena*, que se sirve durante una hora larga a
 * usuarios y a Googlebot. El backend público corre en Render free con
 * spin-down, así que el escenario no es teórico: se observó en vivo una landing
 * cuyo `/hubs` falló mientras `/sitemap/resumen` respondía 586.064 expedientes.
 * Un 404 le dice a Google "esta URL ya no existe"; un 500 le dice "vuelve
 * luego". Ante la duda, la respuesta honesta es la segunda.
 *
 * De ahí la regla de este módulo:
 *
 * - **404/410 y demás 4xx no reintentables** → ausencia. `pedir` devuelve
 *   `null` y el llamante puede hacer `notFound()` con fundamento: la API se
 *   pronunció sobre el dato.
 * - **Error de transporte, 5xx, 408/425/429, 3xx y JSON ilegible** → `pedir`
 *   **lanza** `ErrorApiPublica`. Next falla la regeneración, **conserva la
 *   copia stale** y la vuelve a intentar. Eso es lo que hace que ISR sea seguro:
 *   una página solo se reemplaza por otra que se pudo construir de verdad.
 *
 * Nadie captura esa excepción aguas arriba, y es deliberado. Capturarla para
 * servir una versión degradada la hornearía en la caché ISR durante la hora
 * siguiente, que es exactamente el bug que este módulo existe para no cometer.
 *
 * ## La excepción del build
 *
 * El job `frontend` de CI compila **sin `API_BASE_URL` a propósito** (ver
 * `next.config.ts`), o sea sin backend al que preguntar. Ahí lanzar no protege
 * nada —no existe copia stale que conservar— y solo convertiría un build
 * comprobatorio en un build roto. Por eso `pedir` degrada a "sin dato"
 * únicamente cuando se dan **las dos** condiciones: fase de build y ninguna
 * `API_BASE_URL` configurada.
 *
 * El corolario incómodo es intencionado: un build de Vercel **con**
 * `API_BASE_URL` que no consigue hablar con la API falla el despliegue. Es la
 * respuesta correcta — el despliegue anterior sigue en pie con su sitemap
 * completo, mientras que uno construido a ciegas publicaría un sitemap truncado
 * y hubs en 404, que es un daño que tarda semanas en revertirse.
 */

export type LicitacionPublica = components["schemas"]["LicitacionPublica"];
export type EntradaSitemap = components["schemas"]["EntradaSitemap"];
export type Hubs = components["schemas"]["Hubs"];
export type ResumenSitemap = components["schemas"]["ResumenSitemap"];

/**
 * Origen de la API para llamadas desde el servidor.
 *
 * `next.config.ts` reescribe `/api/*` hacia el backend, pero esos rewrites los
 * aplica el proxy a las peticiones que **entran** desde el navegador: un
 * `fetch` que hace el propio servidor de Next no pasa por ahí. Hay que apuntar
 * al backend directamente.
 */
function origenApi(): string {
  // fdi-allow:localhost-url — fallback de desarrollo para fetch SSR; no es dato renderizado.
  return process.env.API_BASE_URL ?? "http://localhost:8080";
}

/**
 * Cada cuánto se revalida el dato público.
 *
 * Una hora es deliberadamente conservador frente a la cadencia real de ingesta
 * (cada cuatro horas): el coste de servir un anuncio una hora desactualizado es
 * nulo —la página enlaza al original y muestra su fecha de actualización— y a
 * cambio absorbe las ráfagas de rastreo sin tocar Postgres.
 */
const REVALIDAR_SEGUNDOS = 3600;

/**
 * URLs por fichero de sitemap.
 *
 * Vive aquí y no en `app/sitemap.ts` porque el índice (`app/sitemap-index.xml`)
 * tiene que calcular exactamente los mismos tramos: si las dos cifras
 * divergieran, el índice anunciaría ficheros que no existen o se dejaría fuera
 * los últimos, y en los dos casos Search Console lo reporta como error de
 * cobertura sin decir por qué.
 *
 * 10.000 y no el máximo de 50.000 que admite Google: el límite es el techo, no
 * el objetivo. Un tramo más corto evita pedirle al backend medio corpus de una
 * vez y hace que un fallo pierda una porción proporcional, no el fichero entero.
 */
export const SITEMAP_POR_FICHERO = 10_000;

/**
 * La API pública no se pronunció sobre el dato: no llegó respuesta, o la que
 * llegó habla del servidor y no del recurso.
 *
 * Se exporta para poder distinguirla en un `catch` si algún día hiciera falta,
 * no porque hoy alguien la capture: ver el docstring del módulo.
 */
export class ErrorApiPublica extends Error {
  /** Código HTTP recibido, o `null` si la petición ni siquiera llegó a serlo. */
  readonly estado: number | null;

  constructor(ruta: string, estado: number | null, causa?: unknown) {
    super(
      estado === null
        ? `La API pública no respondió a ${ruta}`
        : `La API pública respondió ${estado} a ${ruta}`,
      { cause: causa },
    );
    this.name = "ErrorApiPublica";
    this.estado = estado;
  }
}

/**
 * Intentos por llamada (1 petición + 1 reintento) y espera entre ellos.
 *
 * Acotado a uno y corto a propósito. El reintento cubre lo que sí es ruido —una
 * conexión cortada, un 502 mientras la instancia rota— y el caso observado en
 * vivo era justo ese: dos llamadas simultáneas, una respondió con el corpus
 * entero y la otra no. Lo que **no** puede cubrir es un arranque en frío de
 * Render, que tarda decenas de segundos: para eso está el `throw`, que conserva
 * la copia stale. Reintentar más agrandaría la latencia del render sin cambiar
 * el desenlace, y un bucle sin tope convertiría una caída del backend en un
 * render colgado.
 */
const INTENTOS = 2;
const ESPERA_REINTENTO_MS = 300;

function esperar(ms: number): Promise<void> {
  return new Promise((resolver) => setTimeout(resolver, ms));
}

/**
 * ¿El código HTTP habla del servidor (reintentable) o del recurso (definitivo)?
 *
 * 408/425/429 son 4xx pero significan "ahora no, vuelve"; los 3xx aquí sólo
 * aparecen si un proxy se interpone, que tampoco es una afirmación sobre el
 * dato. El resto de 4xx —404, 410, 400, 422— sí lo son: la API contestó que ese
 * recurso no existe o que la petición no es válida, y en los dos casos la
 * respuesta correcta de la página pública es un 404, no un 500.
 */
function esTransitorio(estado: number): boolean {
  return estado >= 500 || estado < 400 || estado === 408 || estado === 425 || estado === 429;
}

type Resultado<T> =
  | { tipo: "dato"; dato: T }
  | { tipo: "ausencia" }
  | { tipo: "transitorio"; error: ErrorApiPublica };

async function intentar<T>(url: string, ruta: string): Promise<Resultado<T>> {
  let respuesta: Response;
  try {
    respuesta = await fetch(url, {
      next: { revalidate: REVALIDAR_SEGUNDOS },
      headers: { Accept: "application/json" },
    });
  } catch (causa) {
    return { tipo: "transitorio", error: new ErrorApiPublica(ruta, null, causa) };
  }

  if (!respuesta.ok) {
    return esTransitorio(respuesta.status)
      ? { tipo: "transitorio", error: new ErrorApiPublica(ruta, respuesta.status) }
      : { tipo: "ausencia" };
  }

  try {
    return { tipo: "dato", dato: (await respuesta.json()) as T };
  } catch (causa) {
    // Un 200 con cuerpo ilegible es un proxy metiendo su propia página de error,
    // no un dato. Tratarlo como cuerpo vacío publicaría un índice vacío.
    return { tipo: "transitorio", error: new ErrorApiPublica(ruta, respuesta.status, causa) };
  }
}

/**
 * ¿Estamos en el build deliberadamente sin backend?
 *
 * Las dos condiciones a la vez, y se leen en cada llamada y no al cargar el
 * módulo: `NEXT_PHASE` la fija el proceso de build justo antes de arrancar los
 * workers de generación estática, que heredan su entorno.
 */
function buildSinBackend(): boolean {
  return process.env.NEXT_PHASE === PHASE_PRODUCTION_BUILD && !process.env.API_BASE_URL;
}

/**
 * `null` significa **ausencia confirmada por la API**, nunca "no pude saberlo":
 * eso último lanza. Ver el docstring del módulo para el porqué.
 */
async function pedir<T>(ruta: string): Promise<T | null> {
  const url = `${origenApi()}/api/v1/publico${ruta}`;

  let ultimo = await intentar<T>(url, ruta);
  for (let intento = 1; intento < INTENTOS && ultimo.tipo === "transitorio"; intento++) {
    await esperar(ESPERA_REINTENTO_MS);
    ultimo = await intentar<T>(url, ruta);
  }

  if (ultimo.tipo === "dato") return ultimo.dato;
  if (ultimo.tipo === "ausencia") return null;

  if (buildSinBackend()) {
    console.warn(
      `[publico-api] ${ultimo.error.message}. Build sin API_BASE_URL: se sigue sin este dato ` +
        "y la primera revalidación con backend lo rellena.",
    );
    return null;
  }

  throw ultimo.error;
}

/**
 * Anuncio público de un expediente.
 *
 * `null` **solo** si la API dijo que no existe o que no es publicable. Si no se
 * pudo preguntar, esto lanza: la ficha prefiere fallar y seguir sirviendo la
 * copia anterior antes que declararse desaparecida ante un rastreador.
 */
export function obtenerLicitacion(ref: string): Promise<LicitacionPublica | null> {
  return pedir<LicitacionPublica>(`/licitaciones/${encodeURIComponent(ref)}`);
}

/**
 * Listado público, filtrable por slug de comunidad autónoma o prefijo CPV.
 *
 * Devuelve también el `total` real con los filtros aplicados, no el tamaño de
 * la página: es lo que necesita la paginación del hub para saber si hay página
 * siguiente.
 *
 * La lista vacía significa que el backend contestó y no había nada — es la
 * señal con la que el hub decide su `notFound()`. Si no se pudo preguntar, esto
 * lanza en vez de devolver cero resultados.
 */
export async function listarLicitaciones(params: {
  ccaa?: string;
  cpv?: string;
  limit?: number;
  offset?: number;
}): Promise<{ items: LicitacionPublica[]; total: number }> {
  const query = new URLSearchParams();
  if (params.ccaa) query.set("ccaa", params.ccaa);
  if (params.cpv) query.set("cpv", params.cpv);
  query.set("limit", String(params.limit ?? 50));
  query.set("offset", String(params.offset ?? 0));

  const pagina = await pedir<{ items: LicitacionPublica[]; total: number }>(
    `/licitaciones?${query}`,
  );
  return { items: pagina?.items ?? [], total: pagina?.total ?? 0 };
}

/**
 * Comunidades y códigos CPV con volumen suficiente para tener índice.
 *
 * Las listas ya vienen filtradas por umbral del backend. Alimentan las páginas
 * `/licitaciones` y `/cpv`, que son las que reparten autoridad interna hacia
 * los hubs — sin ellas, los hubs solo se descubren por sitemap y ningún enlace
 * les transmite relevancia.
 *
 * Las listas vacías son un hecho del corpus, no un fallo enmascarado: si la API
 * no respondió, esto lanza. El `??` solo cubre el 404 del propio endpoint.
 */
export async function obtenerHubs(): Promise<Hubs> {
  return (await pedir<Hubs>("/hubs")) ?? { ccaa: [], cpv: [] };
}

/**
 * Tamaño y frescura del corpus publicable.
 *
 * `actualizado` es la fecha de incorporación del expediente publicable más
 * reciente. Puede faltar —corpus vacío— y en ese caso el llamante no pinta
 * nada: la franja de la landing existe para respaldar una promesa de frescura,
 * y rellenar el hueco con una fecha inventada sería fabricar justamente la
 * prueba.
 *
 * Ya no cubre el caso "API caída": eso lanza. `total: 0` significa ahora corpus
 * vacío de verdad, que es lo que necesita el sitemap para no encogerse por un
 * fallo de red (ver `contarPublicables`).
 */
export async function obtenerResumenPublico(): Promise<ResumenSitemap> {
  return (await pedir<ResumenSitemap>("/sitemap/resumen")) ?? { total: 0 };
}

/**
 * Cuántas URLs publicables hay. Dimensiona la partición del sitemap.
 *
 * Es el número más peligroso del módulo: de él salen los tramos del índice de
 * sitemaps. Un fallo que se leyera como `0` publicaría un índice con un único
 * fichero, y para Google eso no es "no lo sé" sino "las otras 580.000 URLs han
 * desaparecido". Por eso aquí no hay reserva: si no se pudo contar, lanza.
 */
export async function contarPublicables(): Promise<number> {
  return (await obtenerResumenPublico()).total;
}

/**
 * Un tramo estable de entradas para un fichero de sitemap.
 *
 * La lista vacía solo puede venir de un tramo que el backend declara vacío. Un
 * fallo lanza y deja el fichero sin regenerar: mejor servir el tramo anterior
 * —o un 500 que Google reintenta— que uno truncado en silencio.
 */
export async function entradasSitemap(
  offset: number,
  limit: number,
): Promise<EntradaSitemap[]> {
  return (
    (await pedir<EntradaSitemap[]>(`/sitemap/entradas?offset=${offset}&limit=${limit}`)) ?? []
  );
}
