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
export type PipelineResult = Schemas["PipelineResult"];
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
