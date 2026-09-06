/**
 * Lectura del payload de `/api/v1/health`.
 *
 * El endpoint tiene dos formas históricas —un `checks` explícito o los
 * componentes colgando de la raíz— y la vista tenía que saber leer las dos.
 * Vive aparte porque es la única parte de Observabilidad que no es JSX: son
 * funciones puras sobre la respuesta, y como tales se pueden probar sin montar
 * la pantalla.
 */

export interface HealthCheck {
  status?: string;
  detail?: string;
  [key: string]: unknown;
}

export interface HealthResponse {
  status?: string;
  version?: string;
  uptime?: number;
  checks?: Record<string, HealthCheck | string>;
  [key: string]: unknown;
}

export interface QualityData {
  dlq_count?: number;
  [key: string]: unknown;
}

/** Estados que el backend usa para decir «esto va bien». */
const SANOS = new Set(["ok", "connected", "healthy"]);

/** Claves de la raíz que describen el servicio, no un componente suyo. */
const META = ["status", "version", "uptime"];

/** Componentes que el health viejo devuelve como cadena suelta en la raíz. */
const COMPONENTES_PLANOS = ["db", "redis", "disk"];

export function estadoComponente(value: unknown): "ok" | "error" {
  if (typeof value === "string") {
    return SANOS.has(value.toLowerCase()) ? "ok" : "error";
  }
  if (typeof value === "object" && value !== null) {
    const obj = value as Record<string, unknown>;
    return SANOS.has(String(obj.status ?? "").toLowerCase()) ? "ok" : "error";
  }
  return "error";
}

export function detalleComponente(key: string, value: unknown): string {
  if (typeof value === "string") return `${key}: ${value}`;
  if (typeof value === "object" && value !== null) {
    const obj = value as Record<string, unknown>;
    return obj.detail ? String(obj.detail) : `${key}: ${obj.status ?? "unknown"}`;
  }
  return `${key}: ${String(value)}`;
}

/**
 * Componentes del health, vengan en `checks` o sueltos en la raíz. Sin
 * respuesta devuelve el objeto vacío: la vista decide entonces no pintar la
 * rejilla, en vez de enseñar una sección vacía.
 */
export function extraerChecks(health: HealthResponse | undefined): Record<string, unknown> {
  if (!health) return {};
  if (health.checks && typeof health.checks === "object") {
    return { ...health.checks };
  }
  const checks: Record<string, unknown> = {};
  for (const clave of Object.keys(health)) {
    const valor = health[clave];
    if (!META.includes(clave) && typeof valor === "object" && valor !== null) {
      checks[clave] = valor;
    }
    if (COMPONENTES_PLANOS.includes(clave) && typeof valor === "string") {
      checks[clave] = valor;
    }
  }
  return checks;
}
