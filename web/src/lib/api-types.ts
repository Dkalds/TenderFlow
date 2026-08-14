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
