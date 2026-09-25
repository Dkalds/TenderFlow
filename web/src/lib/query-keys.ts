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

/**
 * Organización de una clave con ámbito, tal y como la devuelve
 * `useActiveOrganizationId`: `number` cuando se sabe cuál, `null` cuando no hay
 * ninguna y la resuelve el backend, y `undefined` mientras todavía no se sabe
 * —la consulta está retenida, pero React Query construye igualmente su clave.
 *
 * Se declara aquí en vez de importarse de `hooks/use-organization` porque ese
 * módulo ya importa de éste (`organizationKeys`) y el ciclo no compraría nada:
 * la caché no distingue los dos últimos estados. React Query hashea la clave
 * con `JSON.stringify`, que convierte el `undefined` de un array en `null`, así
 * que «no se sabe» y «no hay ninguna» caen en la misma entrada. No es un
 * problema: la consulta retenida no escribe en ella, y cuando se resuelve a
 * `null` es exactamente la entrada que le toca.
 */
type OrganizacionDeClave = number | null | undefined;

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

/**
 * Herramientas que leen la ficha del pliego (F2.2, F2.5, F2.6, F2.8).
 *
 * Raíces propias y no bajo `tender-fact-sheet`: el `setQueryData` de la
 * extracción escribe en `fichaKeys.detail`, y una clave hija con otra forma
 * de dato compartiría prefijo con ella sin compartir tipo.
 */
export const simuladorKeys = {
  all: ["simulador-precio"] as const,
  detail: (licitacionId: string, bajas: readonly number[], referencia: number | null) =>
    ["simulador-precio", licitacionId, [...bajas], referencia] as const,
};

export const paginaKeys = {
  all: ["pagina-pliego"] as const,
  detail: (
    licitacionId: string,
    documentoId: number,
    pagina: number,
    inicio: number | null,
    fin: number | null,
  ) => ["pagina-pliego", licitacionId, documentoId, pagina, inicio, fin] as const,
};

export const guionKeys = {
  all: ["guion-oferta"] as const,
  detail: (licitacionId: string) => ["guion-oferta", licitacionId] as const,
};

export const comparacionKeys = {
  all: ["comparar-fichas"] as const,
  /** El orden importa: es el de las columnas que eligió el usuario. */
  fichas: (ids: readonly string[]) => ["comparar-fichas", [...ids]] as const,
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
  /**
   * Diff personal del Resumen (`GET /analytics/resumen/desde-mi-ultima-visita`,
   * F5.4). No se comparte con `resumen/novedades`: es otra pregunta y otro
   * endpoint.
   */
  desdeUltimaVisita: (organizationId: OrganizacionDeClave) =>
    ["analytics", "resumen", "desde-mi-ultima-visita", organizationId] as const,
};

export const radarKeys = {
  all: ["radar"] as const,
  scoring: ["radar", "scoring"] as const,
  scopedScoring: (organizationId: OrganizacionDeClave, tecnologia: string | null) =>
    ["radar", "scoring", organizationId, tecnologia] as const,
  dismissed: (organizationId: OrganizacionDeClave, visibles: readonly string[]) =>
    ["radar", "dismissed-tenders", organizationId, visibles] as const,
  organo: (organo: string | null | undefined) => ["radar", "organo", organo] as const,
  // Estas dos las usa también el prefetch en servidor del Radar
  // (`radar/page.tsx`): son las del Radar que no dependen de la organización
  // activa, que vive en `localStorage` y el servidor no puede leer.
  dismissals: ["radar", "dismissals"] as const,
  proximas: (limite: number) => ["radar", "proximas", limite] as const,
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
  /**
   * Una página concreta del maestro. Lleva dentro los cuatro parámetros que la
   * definen —búsqueda, página, columna y sentido— porque el orden y la
   * paginación los resuelve el servidor: con la clave anterior (sólo la
   * búsqueda) pasar de página o cambiar de columna devolvía la página
   * cacheada, y la tabla se quedaba quieta como si el clic no existiera.
   */
  list: (search: string, page = 0, sort = "importe", order = "desc") =>
    ["empresas", search, page, sort, order] as const,
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
  /**
   * Cruces con un competidor (`GET /competitive/empresas/{key}/contra-mi`,
   * F3.2). Lleva la organización: son las oportunidades de ese equipo.
   */
  contraMi: (empresaKey: string, organizationId: OrganizacionDeClave, meses: number) =>
    ["competitive", "contra-mi", empresaKey, organizationId, meses] as const,
  /** Socios de UTE de un segmento (`GET /competitive/partners`, F3.3). */
  partners: (cpv: string | null, ccaa: string | null) =>
    ["competitive", "partners", cpv, ccaa] as const,
};

// ---------------------------------------------------------------------------
// Búsqueda global (paleta ⌘K)
// ---------------------------------------------------------------------------

export const searchKeys = {
  all: ["search"] as const,
  /** `GET /search/global` (F1.2), por término y organización activa. */
  global: (q: string, organizationId: OrganizacionDeClave) =>
    ["search", "global", q, organizationId] as const,
};

// ---------------------------------------------------------------------------
// Pipeline (pursuits) y organizaciones
// ---------------------------------------------------------------------------

export const pursuitKeys = {
  all: ["pursuits"] as const,
  list: (filters: object) => ["pursuits", "list", filters] as const,
  detail: (id: string) => ["pursuits", "detail", id] as const,
  metrics: ["pursuits", "metrics"] as const,
  /**
   * Las mismas métricas con el periodo que elige Oportunidades → Rendimiento
   * (`period_from`/`period_to` de `GET /pursuits/metrics`).
   *
   * Sin periodo devuelve **exactamente** la clave de `usePursuitMetrics`
   * (`[...metrics, organizationId]`), porque sin periodo es la misma petición:
   * así la tira del tablero y la vista de Rendimiento comparten una entrada de
   * caché en vez de pedir dos veces lo mismo. Con periodo, dos segmentos más y
   * una entrada por ventana; `pursuits` sigue siendo prefijo de todas, que es
   * lo que hace que cerrar una oportunidad las invalide.
   */
  metricsPeriodo: (
    organizationId: OrganizacionDeClave,
    desde: string | null,
    hasta: string | null,
  ) =>
    desde == null && hasta == null
      ? (["pursuits", "metrics", organizationId] as const)
      : (["pursuits", "metrics", organizationId, desde, hasta] as const),
  agenda: ["pursuits", "agenda"] as const,
  /**
   * Contraste ficha × capacidad de una oportunidad
   * (`GET /pursuits/{id}/checklist`, S2.3).
   */
  checklist: (pursuitId: number | string) =>
    ["pursuits", "checklist", String(pursuitId)] as const,
  /**
   * Tareas de una oportunidad (`GET /pursuits/{id}/tasks`, C6.1). Cuelga de la
   * raíz `pursuits` a propósito: crear o completar una tarea recalcula
   * `next_action` en servidor, así que la agenda y la ficha tienen que volver
   * a pedirse — y la invalidación por prefijo que ya hacen las mutaciones de
   * pursuits las alcanza sin enumerarlas.
   */
  tasks: (pursuitId: number | string) => ["pursuits", "tasks", String(pursuitId)] as const,
  /**
   * Propuesta de pesos a partir de los cierres con desglose sellado
   * (`GET /pursuits/weights-proposal`, S3.3). Cuelga de la raíz `pursuits`
   * a propósito: cerrar una oportunidad cambia su base, y la invalidación
   * por prefijo que ya hacen las mutaciones de pursuits la alcanza.
   */
  weightsProposal: ["pursuits", "weights-proposal"] as const,
  /**
   * Cuadro de mando de Dirección (`GET /pursuits/direccion`, F4.2). Lleva la
   * organización porque sin ella el backend resuelve la personal, que no tiene
   * las oportunidades del equipo. Cuelga de `pursuits` por lo mismo que
   * `weightsProposal`: cerrar una oportunidad cambia el win rate.
   */
  direccion: (organizationId: OrganizacionDeClave) =>
    ["pursuits", "direccion", organizationId] as const,
  /**
   * Feed de actividad del equipo (`GET /pursuits/actividad`, F4.5), por
   * organización y persona filtrada. Cuelga de `pursuits`: cada mutación de una
   * oportunidad escribe en el ledger que este feed lee.
   */
  actividad: (organizationId: OrganizacionDeClave, usuario: number | null) =>
    ["pursuits", "actividad", organizationId, usuario] as const,
  /**
   * Kit de presentación de una oportunidad (`GET /pursuits/{id}/kit`, F2.3).
   * Cuelga de `pursuits`: asignar un documento crea una tarea y cambia la
   * próxima acción de la oportunidad, que leen el tablero y la agenda.
   */
  kit: (pursuitId: number | string, organizationId: OrganizacionDeClave) =>
    ["pursuits", "kit", String(pursuitId), organizationId] as const,
  /** Contratos ganados en ejecución (`GET /pursuits/cartera`, F4.3). */
  cartera: (organizationId: OrganizacionDeClave) => ["pursuits", "cartera", organizationId] as const,
  /**
   * Agregados de la cartera (`GET /pursuits/cartera/resumen`). Clave hermana y
   * no hija de `cartera(...)`: son dos respuestas distintas de la misma
   * pantalla y ninguna se deriva de la otra. Lo que invalidan las mutaciones es
   * `pursuits`, que es prefijo de las dos.
   */
  carteraResumen: (organizationId: OrganizacionDeClave) =>
    ["pursuits", "cartera", "resumen", organizationId] as const,
  /**
   * Cronología del contrato de una entrada de cartera
   * (`GET /pursuits/cartera/{id}/eventos`). Va por contrato porque es el
   * detalle del inspector: se pide el del seleccionado, no el de la tabla.
   */
  carteraEventos: (carteraId: number | string, organizationId: OrganizacionDeClave) =>
    ["pursuits", "cartera", "eventos", String(carteraId), organizationId] as const,
};

/**
 * Etiquetas de organización (F1.6). `porObjeto` lleva los ids pedidos porque
 * la respuesta sólo trae los objetos de esa página; `all` es prefijo de todo y
 * es lo que invalidan las mutaciones.
 */
export const etiquetaKeys = {
  all: ["etiquetas"] as const,
  lista: (organizationId: OrganizacionDeClave) => ["etiquetas", "lista", organizationId] as const,
  porObjeto: (organizationId: OrganizacionDeClave, objetoTipo: string, ids: readonly string[]) =>
    ["etiquetas", "por-objeto", organizationId, objetoTipo, [...ids].sort()] as const,
};

export const pursuitCommentKeys = {
  all: ["pursuit-comments"] as const,
  thread: (pursuitId: number | string) => ["pursuit-comments", String(pursuitId)] as const,
};

export const organizationKeys = {
  all: ["organizations"] as const,
  members: (organizationId: OrganizacionDeClave) => ["organization-members", organizationId] as const,
  settings: (organizationId: OrganizacionDeClave) => ["organization-settings", organizationId] as const,
  /**
   * Plantilla de tareas por etapa (F4.6). Nace bajo la raíz, no con literal
   * propio como `members`/`settings`: no hay clientes desplegados que migrar.
   */
  plantillaTareas: (organizationId: OrganizacionDeClave) =>
    ["organizations", "plantilla-tareas", organizationId] as const,
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
