/**
 * Alias con nombre sobre los schemas generados desde OpenAPI.
 *
 * `src/generated/api.d.ts` es 100% generado (`npm run codegen:file`) y solo
 * exporta `paths` / `components` / `operations`. Este módulo NO se genera:
 * da nombres estables a los DTOs que consumen las páginas, de modo que una
 * regeneración del cliente no rompa imports por toda la app.
 *
 * Si el backend renombra un schema, este es el único sitio a tocar.
 */

import type { components } from "@/generated/api";

export type Schemas = components["schemas"];

export type LicitacionSummary = Schemas["LicitacionSummary"];
export type LicitacionDetail = Schemas["LicitacionDetail"];
export type TrendPoint = Schemas["TrendPoint"];
export type TrendsResult = Schemas["TrendsResult"];
export type HistogramBin = Schemas["HistogramBin"];
export type RetenderingResult = Schemas["RetenderingResult"];
export type ForecastVolumeResult = Schemas["ForecastVolumeResult"];
/** El backend lo llama `OverviewResult`; el frontend histórico, `AnalyticsOverview`. */
export type AnalyticsOverview = Schemas["OverviewResult"];
export type ResumenHoyResult = Schemas["ResumenHoyResult"];
export type ResumenNovedadesResult = Schemas["ResumenNovedadesResult"];
export type TimelineScatterResult = Schemas["TimelineScatterResult"];
export type TopLicitacionesResult = Schemas["TopLicitacionesResult"];
export type CalibracionBajaDTO = Schemas["CalibracionBajaDTO"];
export type NotificationsResult = Schemas["NotificationsResult"];
export type AlertItem = Schemas["AlertItem"];
export type EventosFeedResult = Schemas["EventosFeedResult"];
export type EventoFeedItem = Schemas["EventoFeedItem"];

// Renovaciones — primera ola del tipado del contrato (ADR/backlog H2).
// Estas páginas declaraban la forma a mano porque la ruta devolvía
// `dict[str, Any]`; ahora viene del OpenAPI.
export type Renovacion = Schemas["Renovacion"];
export type RenovacionesResult = Schemas["RenovacionesResult"];
export type CarteraEmpresa = Schemas["CarteraEmpresa"];
export type RenovacionesTotales = Schemas["RenovacionesTotales"];
export type RenovacionesResumenResult = Schemas["RenovacionesResumenResult"];

// Watchlist — ola de tipado del contrato (backlog «65 operaciones opacas»).
export type WatchlistRuleOut = Schemas["WatchlistRuleOut"];
export type WatchlistRuleMatch = Schemas["WatchlistRuleMatch"];
export type WatchlistFavoriteItem = Schemas["WatchlistFavoriteItem"];

// Cierre del tipado del contrato (2026-08-03): ALLOWED_OPAQUE llegó a 0 —
// las 128 rutas declaran DTO. Aliases de las superficies que las páginas
// consumen con más frecuencia; el resto se importa como Schemas["..."].
export type EmpresaListItem = Schemas["EmpresaListItem"];
export type EmpresaDetail = Schemas["EmpresaDetail"];
export type EmpresasStats = Schemas["EmpresasStats"];
export type MetaFilters = Schemas["MetaFilters"];
export type SavedFilter = Schemas["SavedFilter"];
export type FeedbackQueueItem = Schemas["FeedbackQueueItem"];
export type ModelInfoResult = Schemas["ModelInfoResult"];
export type CuotaResult = Schemas["CuotaResult"];
export type HhiResult = Schemas["HhiResult"];
export type BajasResult = Schemas["BajasResult"];

// Superficies que los hooks declaraban a mano con su propia `interface`. Un
// tipo escrito a mano compila aunque la API nunca envíe ese campo, y el valor
// llega a pantalla como `undefined` — ya pasó dos veces (ver el ítem de
// backlog). Derivarlos del esquema hace que `npm run typecheck` delate la
// divergencia en vez de la UI.
export type SourceFreshness = Schemas["SourceFreshness"];
export type SourceFreshnessResult = Schemas["SourceFreshnessResult"];
export type PriceScenariosResult = Schemas["PriceScenariosResult"];
export type PriceScenario = Schemas["PriceScenario"];
export type HistoricalDistribution = Schemas["HistoricalDistribution"];
export type OrganizationSummary = Schemas["OrganizationSummary"];
export type OrganizationMembershipOut = Schemas["OrganizationMembershipOut"];
export type OrganizationMemberInvite = Schemas["OrganizationMemberInvite"];
export type OrganizationMembershipUpsert = Schemas["OrganizationMembershipUpsert"];
export type AskModelInfo = Schemas["AskModelInfo"];
export type TenderFactSheet = Schemas["TenderFactSheet"];
export type TenderFactSheetRecord = Schemas["TenderFactSheetRecord"];
export type EvidenceRef = Schemas["EvidenceRef"];
/** Estado efímero del BackgroundTask de extracción (extract-async + polling). */
export type FactSheetExtractionState = Schemas["FactSheetExtractionState"];
/**
 * Familias de hechos de la ficha de pliego. El backend las tipa por separado
 * (un criterio de adjudicación tiene `weight_pct`, un aval tiene `amount_eur`);
 * aplanarlas en un solo tipo es lo que hacía `use-tender-fact-sheet` a mano.
 */
export type FactItem = Schemas["FactItem"];
export type WeightedCriterion = Schemas["WeightedCriterion"];
export type MonetaryFact = Schemas["MonetaryFact"];
export type TeamRequirement = Schemas["TeamRequirement"];
export type DeadlineFact = Schemas["DeadlineFact"];
export type LotFact = Schemas["LotFact"];
export type CertificationRequirement = Schemas["CertificationRequirement"];
export type ServiceLevelFact = Schemas["ServiceLevelFact"];
export type TechnologyMention = Schemas["TechnologyMention"];
/** Lo que devuelve `POST /watchlist/items`: sin los campos enriquecidos del GET. */
export type WatchlistFavoriteCreated = Schemas["WatchlistFavoriteCreated"];
/** Solo la creación devuelve `secret`, y una única vez. */
export type WebhookCreateResponse = Schemas["WebhookCreateResponse"];
export type WebhookDelivery = Schemas["WebhookDelivery"];
export type WebhookPingResult = Schemas["WebhookPingResult"];
export type WebhookEventTypes = Schemas["WebhookEventTypes"];
export type WebhookOut = Schemas["WebhookOut"];
export type ResolucionOut = Schemas["ResolucionOut"];
export type TimelineResult = Schemas["TimelineResult"];
export type PrediccionBajaResult = Schemas["PrediccionBajaResult"];

// Ola 1 del tipado del cliente OpenAPI (`src/hooks/**`, backlog «migrar al
// cliente tipado»). Los hooks de pursuits y radar importaban
// `components["schemas"][...]` directamente de `@/generated/api`, saltándose
// esta capa: una regeneración que renombre un schema rompía los imports en
// cada hook en vez de en este único fichero.
export type PursuitDetail = Schemas["PursuitDetail"];
export type PursuitListResponse = Schemas["PursuitListResponse"];
export type PursuitMetrics = Schemas["PursuitMetrics"];
export type PursuitCreate = Schemas["PursuitCreate"];
export type PursuitUpdate = Schemas["PursuitUpdate"];
// Hilo de comentarios de una oportunidad (v97): el chat del equipo sobre un
// expediente. `can_delete` viene calculado por la API para quien pregunta.
export type PursuitCommentOut = Schemas["PursuitCommentOut"];
export type PursuitCommentCreate = Schemas["PursuitCommentCreate"];
export type PursuitCommentListResponse = Schemas["PursuitCommentListResponse"];
export type PipelineAgendaResponse = Schemas["PipelineAgendaResponse"];
export type PipelineAgendaItem = Schemas["PipelineAgendaItem"];
export type ScoredOpportunity = Schemas["ScoredOpportunity"];
export type ScoringResult = Schemas["ScoringResult"];
export type ScoringSignalsHealth = Schemas["ScoringSignalsHealth"];

// Envoltorios de respuesta que los hooks declaraban como `interface` local
// (`LastExtractionResponse`, `DismissalsResponse`, `{ items: … }` inline).
export type LastExtraction = Schemas["LastExtraction"];
export type RadarDismissalsResult = Schemas["RadarDismissalsResult"];
export type RadarDismissalBody = Schemas["RadarDismissalBody"];
export type WatchlistFavoritesResult = Schemas["WatchlistFavoritesResult"];

// Cuerpos de petición de webhooks: el alta y la edición los describía el hook
// a mano, con `event_types` obligatorio donde la API lo tiene opcional.
export type WebhookCreate = Schemas["WebhookCreate"];
export type WebhookUpdate = Schemas["WebhookUpdate"];

// Adjuntos (pliegos) de una licitación. El bloque de documentos declaraba su
// propia `interface Documento` a mano — justo el patrón que este fichero existe
// para evitar: `status` viajaba en la respuesta desde el principio y la UI no
// lo miraba, así que los enlaces caducados se pintaban como los sanos.
export type DocumentoSummary = Schemas["DocumentoSummary"];
export type DocumentosResult = Schemas["DocumentosResult"];

// Calendario de compromisos y configuración de la organización, añadidos con
// las mejoras de producto de 2026-09. El enlace del ICS es una ruta firmada:
// el cliente le antepone su propio origen (ver `calendario-suscripcion.tsx`).
export type CalendarioEnlace = Schemas["CalendarioEnlace"];
export type OrganizationSettings = Schemas["OrganizationSettings"];
export type OrganizationSettingsOut = Schemas["OrganizationSettingsOut"];
