/**
 * Lectura del payload de `/api/v1/health`.
 *
 * Vive aparte porque es la única parte de la vista que no es JSX: son funciones
 * puras sobre la respuesta, y como tales se prueban sin montar la pantalla
 * (`__tests__/health-checks.test.ts`).
 *
 * La respuesta es plana —`status` y una cadena por componente (`db`, `redis`,
 * `disk`, `schema_revision`)— y **llega con HTTP 200 aunque el servicio esté
 * degradado** (ver `api/routes/health.py`: solo `/ready` responde 503, y solo
 * por la BD). Por eso el estado global se lee de `status` y no de que la
 * llamada haya ido bien: durante meses la cabecera dijo «Todos los servicios
 * responden» con el esquema seis revisiones por detrás.
 */

import type { Schemas } from "@/lib/api-types";

/**
 * Tolerante a propósito: la tarjeta de «Estado del sistema» vuelca la respuesta
 * clave a clave, así que una clave nueva del backend se enseña sin tocar nada.
 */
export type HealthResponse = Partial<Schemas["HealthResponse"]> & Record<string, unknown>;

export type EstadoComponente = "ok" | "aviso" | "error" | "sin_dato";

/** Lo que dice la cabecera. `comprobando` = aún no ha llegado ninguna respuesta. */
export type EstadoGlobalSalud = "ok" | "degradado" | "error" | "comprobando";

export interface ComponenteSalud {
  clave: string;
  nombre: string;
  estado: EstadoComponente;
  /** El valor tal como lo manda la API: es lo que se busca en un log. */
  detalle: string;
}

/** Estados que el backend usa para decir «esto va bien». */
const SANOS = new Set(["ok", "connected", "healthy"]);

/** «No se mide», que no es lo mismo que «va mal». */
const SIN_MEDIR = ["unknown", "unconfigured"];

/** Componentes del health, en el orden en que se leen, con su nombre. */
const COMPONENTES: readonly [clave: string, nombre: string][] = [
  ["db", "Base de datos"],
  ["redis", "Redis"],
  ["disk", "Disco"],
  ["schema_revision", "Esquema de la base de datos"],
];

function texto(valor: unknown): string {
  if (typeof valor === "string") return valor.trim();
  if (typeof valor === "object" && valor !== null) {
    const estado = (valor as Record<string, unknown>).status;
    return typeof estado === "string" ? estado.trim() : "";
  }
  return "";
}

export function estadoComponente(valor: unknown): EstadoComponente {
  const crudo = texto(valor).toLowerCase();
  // El esquema responde «ok (v146_…)» y el disco «low (120 MB free…)»: el
  // estado es la primera palabra y el paréntesis, su detalle.
  const estado = crudo.split(/[\s(]/, 1)[0];
  if (!estado || SIN_MEDIR.includes(estado)) return "sin_dato";
  if (SANOS.has(estado)) return "ok";
  if (estado === "error") return "error";
  return "aviso";
}

/**
 * Los componentes que la respuesta trae, y solo esos: uno que el backend no
 * manda no se pinta a «sin dato», porque nadie ha dicho que exista.
 */
export function componentesDeSalud(health: HealthResponse | undefined): ComponenteSalud[] {
  if (!health) return [];
  return COMPONENTES.filter(([clave]) => health[clave] != null).map(([clave, nombre]) => ({
    clave,
    nombre,
    estado: estadoComponente(health[clave]),
    detalle: texto(health[clave]),
  }));
}

export function estadoGlobal(
  health: HealthResponse | undefined,
  { cargando, fallo }: { cargando: boolean; fallo: boolean },
): EstadoGlobalSalud {
  if (cargando) return "comprobando";
  if (fallo || !health) return "error";
  if (typeof health.status === "string" && health.status) {
    return SANOS.has(health.status.toLowerCase()) ? "ok" : "degradado";
  }
  // Sin `status` no hay veredicto del backend: se deduce de lo que sí vino.
  const sano = componentesDeSalud(health).every((c) => c.estado === "ok" || c.estado === "sin_dato");
  return sano ? "ok" : "degradado";
}
