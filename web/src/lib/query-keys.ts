/**
 * Registro único de claves de React Query.
 *
 * # Por qué existe
 *
 * Hasta 2026-09 no había convención: convivían cuatro fábricas locales
 * (`licitacionKeys`, `pursuitKeys`, `pursuitCommentKeys`,
 * `organizationSettingsKeys`) con ~80 literales escritos a mano en el sitio de
 * uso. Una clave literal no la comprueba nadie, así que fallaba en las dos
 * direcciones:
 *
 * - **Dos claves iguales con dos `queryFn` distintas.** `["ask-models"]` estaba
 *   en `hooks/use-ask.ts` (tipada vía `apiGet`, `meta: { silent: true }`) y en
 *   `investigador/page.tsx` (`fetch` crudo, sin tipar). React Query cachea por
 *   clave, no por función: ganaba la que montara primero, así que el contenido
 *   del selector de modelos dependía de en qué orden se abriera la pantalla.
 * - **Dos claves distintas para el mismo dato.** `/analytics/quality` se pedía
 *   con `["analytics-quality"]`, `["analytics-quality-admin"]`,
 *   `["analytics-quality-obs"]` y `["analytics","quality"]`: cuatro entradas de
 *   caché y cuatro peticiones para una respuesta idéntica.
 *
 * # Convención
 *
 * Una fábrica por recurso, con el nombre del recurso como primer segmento y
 * `as const` en todo el retorno (React Query compara por estructura; el
 * `readonly` evita que alguien mute la clave que ya está en la caché).
 *
 *     export const algoKeys = {
 *       all: ["algo"] as const,                       // raíz: invalida el recurso entero
 *       lista: (f: Filtros) => ["algo", "lista", f] as const,
 *       detalle: (id: string) => ["algo", "detalle", id] as const,
 *     };
 *
 * La raíz `all` es lo que hace que `invalidateQueries({ queryKey: algoKeys.all })`
 * alcance a listas y detalles a la vez: React Query hace *prefix matching*.
 *
 * # Regla
 *
 * Una `queryKey` nueva se declara **aquí**, no en el sitio de uso. Si un dato
 * se pide desde dos ficheros, el que se comparte es el hook, no solo la clave:
 * dos `queryFn` distintas bajo la misma clave es el bug de arriba.
 */

// ---------------------------------------------------------------------------
// Sesión y metadatos
// ---------------------------------------------------------------------------

export const authKeys = {
  all: ["auth"] as const,
  me: ["auth", "me"] as const,
};

export const metaKeys = {
  all: ["meta"] as const,
  /** Catálogos de filtros (`GET /meta/filters`). */
  filters: ["meta", "filters"] as const,
  lastExtraction: ["meta", "last-extraction"] as const,
};

// ---------------------------------------------------------------------------
// Licitaciones y su ficha
// ---------------------------------------------------------------------------

export const licitacionKeys = {
  all: ["licitacion"] as const,
  detail: (id: string) => ["licitacion", id] as const,
};

export const licitacionesKeys = {
  all: ["licitaciones"] as const,
  list: (params: Record<string, string>) => ["licitaciones", params] as const,
};

export const documentosKeys = {
  all: ["documentos"] as const,
  /** Compartida por `DocumentosBlock` y la ficha: una sola petición. */
  byLicitacion: (licitacionId: string) => ["documentos", licitacionId] as const,
};

export const eventosKeys = {
  all: ["eventos"] as const,
  byLicitacion: (licitacionId: string) => ["eventos", licitacionId] as const,
};

export const resolucionesKeys = {
  all: ["resoluciones"] as const,
  byLicitacion: (licitacionId: string) => ["resoluciones", licitacionId] as const,
};

export const tecnologiasKeys = {
  all: ["tecnologias"] as const,
  byLicitacion: (licitacionId: string) => ["tecnologias", licitacionId] as const,
};

export const prediccionKeys = {
  baja: (licitacionId: string) => ["prediccion-baja", licitacionId] as const,
  calibracion: ["calibracion-baja"] as const,
  escenarios: (licitacionId: string | null) => ["price-scenarios", licitacionId] as const,
};

export const fichaKeys = {
  all: ["tender-fact-sheet"] as const,
  detail: (licitacionId: string) => ["tender-fact-sheet", licitacionId] as const,
  estado: (licitacionId: string) => ["tender-fact-sheet-estado", licitacionId] as const,
};

// ---------------------------------------------------------------------------
// Analítica
// ---------------------------------------------------------------------------

export const analyticsKeys = {
  all: ["analytics"] as const,
  /**
   * Una sola clave para `GET /analytics/quality`.
   *
   * Tenía cuatro (`analytics-quality`, `-admin`, `-obs`, `["analytics","quality"]`)
   * para una respuesta idéntica: cuatro entradas de caché y cuatro peticiones.
   */
  quality: ["analytics", "quality"] as const,
  sourceFreshness: ["analytics", "source-freshness"] as const,
  overview: (params: Record<string, string>) =>
    ["analytics", "overview", "/api/v1/analytics/overview", params] as const,
  /** Score de las filas visibles de `detalle` (batch por `id_externo`). */
  scoringBatch: (ids: readonly string[]) => ["scoring-batch", ids] as const,
};

export const radarKeys = {
  all: ["radar"] as const,
  scoring: ["radar", "scoring"] as const,
  scopedScoring: (organizationId: number | null, tecnologia: string | null) =>
    ["radar", "scoring", organizationId, tecnologia] as const,
  dismissed: (organizationId: number | null, visibles: readonly string[]) =>
    ["radar", "dismissed-tenders", organizationId, visibles] as const,
  organo: (organo: string | null | undefined) => ["radar", "organo", organo] as const,
};

// ---------------------------------------------------------------------------
// Copiloto / investigador
// ---------------------------------------------------------------------------

export const askKeys = {
  all: ["ask"] as const,
  /**
   * Catálogo de modelos LLM. Una sola clave **y una sola `queryFn`**: la
   * tipada de `hooks/use-ask.ts`. La copia sin tipar de `investigador` se
   * retiró — ver la cabecera de este fichero.
   */
  models: ["ask-models"] as const,
};

// ---------------------------------------------------------------------------
// Watchlist y reglas
// ---------------------------------------------------------------------------

export const watchlistKeys = {
  all: ["watchlist"] as const,
  items: ["watchlist-items"] as const,
  rules: ["watchlist-rules"] as const,
  combined: (ruleIds: string) => ["watchlist-combined", ruleIds] as const,
  /** Empresas seguidas (`GET /competitive/watchlist`). */
  empresas: ["watchlist-empresas"] as const,
};

// ---------------------------------------------------------------------------
// Empresas y competencia
// ---------------------------------------------------------------------------

export const empresasKeys = {
  all: ["empresas"] as const,
  list: (search: string) => ["empresas", search] as const,
  stats: ["empresas-stats"] as const,
  reviews: ["empresa-reviews"] as const,
  detail: (empresaId: number | string) => ["empresa-detail", empresaId] as const,
  perfil: (empresaId: number | string) => ["empresa-perfil", empresaId] as const,
};

export const competitiveKeys = {
  all: ["competitive"] as const,
  companyProfile: (empresaId: number | string, scopeQuery: string) =>
    ["competitive-company-profile", empresaId, scopeQuery] as const,
  companyAwards: (empresaId: number | string, params: string | Record<string, string>) =>
    ["competitive-company-awards", empresaId, params] as const,
};

// ---------------------------------------------------------------------------
// Pipeline (pursuits) y organizaciones
// ---------------------------------------------------------------------------

export const pursuitKeys = {
  all: ["pursuits"] as const,
  list: (filters: object) => ["pursuits", "list", filters] as const,
  detail: (id: string) => ["pursuits", "detail", id] as const,
  metrics: ["pursuits", "metrics"] as const,
  agenda: ["pursuits", "agenda"] as const,
};

export const pursuitCommentKeys = {
  all: ["pursuit-comments"] as const,
  thread: (pursuitId: number | string) => ["pursuit-comments", String(pursuitId)] as const,
};

export const organizationKeys = {
  all: ["organizations"] as const,
  members: (organizationId: number | null) => ["organization-members", organizationId] as const,
  settings: (organizationId: number | null) => ["organization-settings", organizationId] as const,
};

export const perfilKeys = {
  /** Perfil de scoring del usuario (`GET /me/profile`). */
  me: ["me", "profile"] as const,
};

export const calendarioKeys = {
  enlace: ["calendario", "enlace"] as const,
};

// ---------------------------------------------------------------------------
// Operación (Ops)
// ---------------------------------------------------------------------------

export const feedbackKeys = {
  all: ["feedback"] as const,
  /** Compartida por la tira de salud de Ops y por Active Learning. */
  stats: ["feedback-stats"] as const,
  modelInfo: ["feedback-model-info"] as const,
  queue: (strategy: string) => ["feedback-queue", strategy] as const,
};

export const webhookKeys = {
  all: ["webhooks"] as const,
  eventTypes: ["webhooks", "event-types"] as const,
  deliveries: (webhookId: number | null) => ["webhooks", "deliveries", webhookId] as const,
};

export const adminKeys = {
  users: ["admin-users"] as const,
  apiKeys: ["api-keys"] as const,
  health: ["health"] as const,
  solicitudes: {
    all: ["admin-solicitudes-acceso"] as const,
    vista: (vista: "pendiente" | "historico") => ["admin-solicitudes-acceso", vista] as const,
  },
  accessGrants: ["admin-access-grants"] as const,
};

export const renovacionesKeys = {
  all: ["renovaciones"] as const,
  lista: (meses: number, tecnologia: string | null) =>
    ["renovaciones", meses, tecnologia] as const,
  resumen: (meses: number, tecnologia: string | null) =>
    ["renovaciones-resumen", meses, tecnologia] as const,
};
