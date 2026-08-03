/**
 * Datos compartidos por los specs E2E.
 *
 * Todo lo de aquí procede de `scripts/seed_dev.py`, que es determinista: si
 * cambiás el seed, cambiá esto a la vez o los specs empiezan a fallar por el
 * motivo equivocado.
 */

export const DEMO_USER = {
  email: "demo@tenderflow.dev",
  password: "demo1234!",
} as const;

/** Usuario con `is_admin`: sin él las rutas de administración solo se pueden
 *  verificar en su estado "Acceso restringido". */
export const ADMIN_USER = {
  email: "admin@tenderflow.dev",
  password: "admin1234!",
} as const;

export const STORAGE_STATE_USER = "playwright/.auth/user.json";
export const STORAGE_STATE_ADMIN = "playwright/.auth/admin.json";

/** Primera licitación del seed (`_SAMPLE_LICITACIONES[0]`). */
export const SEED_LICITACION = {
  id: "SEED-2026-001",
  titulo: "Suministro de equipos informáticos para administración pública",
  organo: "Ministerio de Hacienda",
  /** La que el Radar prioriza primero con los datos sembrados. */
  tituloRadar: "Implantación de sistema ERP para gestión municipal",
} as const;

/** Número de licitaciones que siembra `scripts/seed_dev.py`. */
export const SEED_TOTAL_LICITACIONES = 15;

/** Prefijo común a las 15 licitaciones sembradas. */
export const SEED_PREFIX = "SEED-2026-";

/** Id que no existe: sirve para comprobar el estado vacío. */
export const ID_INEXISTENTE = "NO-EXISTE-999";
