/**
 * Telemetría de producto: el catálogo completo y el único sitio que llama a
 * `track`.
 *
 * Por qué existe
 * --------------
 * `@vercel/analytics` ya estaba en el bundle y `<Analytics />` montado en el
 * layout raíz, pero en agosto de 2026 sólo había **tres** `track()` en todo
 * `web/src` y las tres vivían en la superficie pública (el CTA de solicitar
 * acceso y su resultado). Dentro del producto —14 espacios, 162 endpoints— no
 * se medía absolutamente nada: no había forma de saber qué se usa, qué se
 * abandona ni qué se puede retirar sin romperle el día a nadie.
 *
 * Reglas de este módulo (en orden de importancia)
 * ----------------------------------------------
 * 1. **Privacidad, innegociable.** Aquí no entra nunca un email, un nombre, un
 *    id de usuario o de organización, un `id_externo` de licitación, un título,
 *    el texto de una pregunta a `/ask`, un término de búsqueda ni un filtro
 *    escrito por el usuario. Sólo **dimensiones categóricas de cardinalidad
 *    baja** cuyos valores posibles se puedan enumerar leyendo este fichero
 *    (espacio, acción, modo, resultado, formato). Si para responder una
 *    pregunta hace falta un identificador, la pregunta se responde en backend
 *    con los datos que ya tiene, no aquí. El filtro de `PROPIEDADES_PERMITIDAS`
 *    es la red de seguridad, no el permiso: una propiedad nueva se añade
 *    primero al catálogo y sólo entonces se manda.
 * 2. **Menos eventos bien elegidos que muchos eventos.** Se instrumentan
 *    preguntas de negocio, no clics. Cada entrada del catálogo lleva la suya
 *    escrita. Si el evento 11 no responde una pregunta que hoy no se pueda
 *    responder, no entra.
 * 3. **Fallar en silencio.** Un bloqueador de anuncios, un `track` que no
 *    cargó o un `window` inexistente no pueden tumbar una mutación del
 *    producto: todo va envuelto en `try/catch` y no propaga nada.
 * 4. **Nada de esto corre en servidor.** El módulo se corta en seco si no hay
 *    `window`, así que importarlo desde un componente de servidor (o desde un
 *    módulo que uno importe) no rompe el prerender de la superficie pública.
 *    Aun así: no lo hagas. Los emisores son hooks y componentes cliente.
 *
 * Para la primera poda
 * --------------------
 * La auditoría que motivó este módulo encontró endpoints de la API **sin
 * ningún consumidor** en `web/src` (excluido `src/generated/`):
 *
 *   - `GET /api/v1/analytics/compare-periods`  → 0 referencias
 *   - `GET /api/v1/analytics/resumen/sankey`   → 0 referencias
 *   - `GET /api/v1/analytics/resumen/top`      → sólo mencionado en un
 *     comentario de `lib/navigation.ts`, ningún `fetch`
 *
 * "Sin consumidor en el frontend" no es lo mismo que "sin uso" —puede haber
 * clientes externos o trabajos internos—, así que esto es el punto de partida
 * de la conversación de retirada, no la decisión. Los eventos de abajo son la
 * otra mitad: dicen qué **sí** se usa, para que podar deje de ser una apuesta.
 */

import { track } from "@vercel/analytics";
import { getJSON, setJSON } from "@/lib/storage";

/**
 * Respuesta a "¿es la primera vez?" cuando la respuesta se sella en el
 * navegador. `desconocido` no es relleno: distingue "ya lo había hecho" de "no
 * pude saberlo", que es lo que pasa en modo privado.
 */
export type PrimeraVez = "si" | "no" | "desconocido";

/**
 * Catálogo de eventos. El nombre del evento es una clave de esta interfaz, así
 * que un typo no compila, y las propiedades de cada uno son uniones de
 * literales: tampoco compila un valor que no esté previsto.
 */
export interface EventosProducto {
  /**
   * ¿Entra la gente? Es el denominador de todo lo demás: sin él, "20 exports"
   * no se sabe si son muchos o poquísimos. `metodo` separa contraseña de
   * segundo factor y de alta nueva.
   */
  sesion_iniciada: { metodo: "password" | "totp" | "registro" };
  /**
   * ¿Qué espacios se visitan? La clave estable de `ConsoleSpace` (existe
   * justamente para esto) sobrevive a renombrar el slug o mover la ruta, cosa
   * que el pageview por URL no hace. Mide navegación desde el rail, no visitas
   * totales: la entrada directa por URL o por la paleta no pasa por aquí.
   */
  espacio_abierto: { espacio: string; origen: "rail" | "rail_movil" };
  /**
   * ¿Se usa el Radar para decidir, o sólo para mirar? Descartar es la decisión
   * que cuesta; recuperar dice cuánto se arrepiente la gente de haberla tomado.
   */
  radar_triaje: { accion: "descartar" | "recuperar" };
  /**
   * ¿Se queda alguien con la señal? El seguimiento se puede activar desde el
   * Radar y desde el Detalle y aquí no se distingue: la pregunta es si la
   * licitación se guarda, no desde qué pantalla.
   */
  licitacion_seguida: { accion: "seguir" | "dejar_de_seguir" };
  /**
   * Activación: el momento en que alguien pasa de mirar el mercado a trabajar
   * una oportunidad concreta. `primera_vez` separa esa activación del uso de
   * quien ya lo hace a diario.
   */
  pursuit_creado: { primera_vez: PrimeraVez };
  /**
   * ¿El pipeline se mueve o se abandona en cuanto se crea? `estado` es uno de
   * los ocho del workflow (`PURSUIT_STATUSES`): categórico y cerrado.
   */
  pursuit_estado_cambiado: { estado: string };
  /**
   * Activación por la otra puerta: la primera regla de watchlist es lo que
   * convierte el producto en algo que trabaja solo.
   *
   * PENDIENTE DE CABLEAR: el `POST /watchlist/rules` vive en
   * `app/(dashboard)/mi-watchlist/page.tsx` (mutación `crear`), fichero que no
   * pertenecía a este trabajo. El evento se declara aquí para que cablearlo sea
   * una línea en el `onSuccess` de esa mutación:
   * `registrarEvento("regla_creada", { primera_vez: primeraVez("regla") })`.
   */
  regla_creada: { primera_vez: PrimeraVez };
  /**
   * ¿Se usa el asistente, y le sirve a alguien? `resultado: "degradado"` es la
   * respuesta sin síntesis del LLM: si domina, el asistente aparenta funcionar
   * y no funciona. Nunca viaja la pregunta ni la licitación preguntada, sólo si
   * era sobre el corpus o sobre una licitación.
   */
  asistente_usado: {
    modo: "pregunta" | "resumen";
    ambito: "corpus" | "licitacion";
    resultado: "ok" | "degradado" | "error";
  };
  /**
   * ¿La gente se lleva el dato? Es la señal más fuerte de que una pantalla
   * sirve de verdad. `recurso` sale de la ruta del endpoint depurada (ver
   * `dimensionesDeDescarga`), nunca de la query: ahí van los filtros del
   * usuario.
   */
  export_lanzado: { formato: "csv" | "xlsx" | "otro"; recurso: string };
}

export type EventoProducto = keyof EventosProducto;

/**
 * Propiedades que cada evento puede mandar, en tiempo de ejecución.
 *
 * Duplica lo que ya dice el tipo a propósito: los tipos desaparecen al
 * compilar, y esta lista es lo único que sigue en pie si un `as` mal puesto o
 * un objeto construido dinámicamente cuela una clave de más. El `satisfies`
 * evita que las dos mitades se desincronicen — un evento nuevo sin entrada aquí
 * no compila.
 */
export const PROPIEDADES_PERMITIDAS = {
  sesion_iniciada: ["metodo"],
  espacio_abierto: ["espacio", "origen"],
  radar_triaje: ["accion"],
  licitacion_seguida: ["accion"],
  pursuit_creado: ["primera_vez"],
  pursuit_estado_cambiado: ["estado"],
  regla_creada: ["primera_vez"],
  asistente_usado: ["modo", "ambito", "resultado"],
  export_lanzado: ["formato", "recurso"],
} as const satisfies Record<EventoProducto, readonly string[]>;

/** Tope defensivo de longitud: un valor largo delata que alguien coló texto. */
const MAX_LONGITUD_VALOR = 48;

/**
 * Emite un evento de producto. Único punto del frontend que llama a `track`.
 *
 * No devuelve nada ni indica si se mandó: quien lo llama no puede tomar
 * decisiones a partir de la telemetría, sólo emitirla.
 */
export function registrarEvento<E extends EventoProducto>(
  nombre: E,
  propiedades: EventosProducto[E],
): void {
  // Sin `window` no hay nada que medir (prerender, tests de servidor): salir
  // aquí es lo que permite que este módulo se pueda importar desde cualquier
  // sitio sin romper el build de la superficie pública.
  if (typeof window === "undefined") return;

  try {
    const permitidas: readonly string[] = PROPIEDADES_PERMITIDAS[nombre];
    const limpias: Record<string, string> = {};
    for (const [clave, valor] of Object.entries(propiedades as Record<string, unknown>)) {
      if (!permitidas.includes(clave)) continue;
      // Sólo strings cortos: cualquier otra cosa (objeto, número con id dentro,
      // texto libre) se descarta en vez de mandarse "por si acaso".
      if (typeof valor !== "string" || valor === "" || valor.length > MAX_LONGITUD_VALOR) continue;
      limpias[clave] = valor;
    }
    track(nombre, limpias);
  } catch {
    // Bloqueador de anuncios, script no cargado, cuota agotada. La telemetría
    // es lo primero que se sacrifica: nunca al revés.
  }
}

/**
 * ¿Es la primera vez que este navegador hace `marca`?
 *
 * Es la única forma de separar activación de rutina sin identificar a nadie:
 * un sello booleano local, sin id de usuario ni de sesión. Con eso viene la
 * letra pequeña, y conviene leerla antes de interpretar el número: es **por
 * navegador**, así que el mismo usuario en dos equipos se activa dos veces, y
 * borrar los datos del sitio lo reactiva. Sirve para ver la forma de la curva,
 * no para contar personas.
 *
 * Si no se pudo escribir el sello (modo privado, almacenamiento bloqueado) la
 * respuesta es `desconocido`: decir "sí" cada vez inflaría la activación hasta
 * volverla mentira.
 */
export function primeraVez(marca: string): PrimeraVez {
  const clave = `telemetria:primera:${marca}`;
  if (getJSON<boolean>(clave, false)) return "no";
  return setJSON(clave, true) ? "si" : "desconocido";
}

/**
 * Segmento de ruta que se puede mandar tal cual: sólo minúsculas y guiones.
 *
 * Descarta cualquier cosa con dígitos, mayúsculas o escapes de URL, que es
 * exactamente la forma de los identificadores del dominio (`PA-S 2026/000058`
 * llega como `PA-S%202026%2F000058`) y de los ids numéricos.
 */
const SEGMENTO_SEGURO = /^[a-z][a-z-]*$/;

/**
 * Dimensiones de una descarga a partir de su URL.
 *
 * De la URL sólo sobreviven dos cosas: el formato y la ruta depurada del
 * endpoint. La query **entera** se tira, y no por pereza: ahí viajan los
 * filtros activos, que incluyen el término de búsqueda que escribió el usuario
 * y el órgano o la empresa que está mirando.
 */
export function dimensionesDeDescarga(url: string): EventosProducto["export_lanzado"] {
  const [ruta = "", query = ""] = url.split("?");
  const declarado = new URLSearchParams(query).get("format");
  const formato = declarado === "csv" || declarado === "xlsx" ? declarado : "otro";
  const recurso = ruta
    .replace(/^\/?api\/v\d+\//, "")
    .split("/")
    .filter((segmento) => SEGMENTO_SEGURO.test(segmento))
    .join("/");
  return { formato, recurso: recurso || "otro" };
}
