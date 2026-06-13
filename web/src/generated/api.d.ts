/**
 * Auto-generated API types from FastAPI OpenAPI schema.
 *
 * DO NOT EDIT — regenerate with: npm run codegen
 *
 * This is a placeholder with manually typed paths matching the existing
 * FastAPI endpoints + the new analytics endpoints. Once the API is running,
 * run `npm run codegen` to replace this with the real generated types.
 */

export interface paths {
  "/api/v1/health": {
    get: {
      responses: {
        200: {
          content: {
            "application/json": { status: string; version: string };
          };
        };
      };
    };
  };

  "/api/v1/auth/login": {
    post: {
      requestBody: {
        content: {
          "application/json": {
            email: string;
            password: string;
          };
        };
      };
      responses: {
        200: {
          content: {
            "application/json": {
              user_id: string;
              email: string;
              display_name: string | null;
              is_admin: boolean;
            };
          };
        };
        401: {
          content: {
            "application/json": { detail: string };
          };
        };
      };
    };
  };

  "/api/v1/auth/me": {
    get: {
      responses: {
        200: {
          content: {
            "application/json": {
              user_id: string;
              email: string;
              display_name: string | null;
              is_admin: boolean;
              provider: string;
            };
          };
        };
        401: {
          content: {
            "application/json": { detail: string };
          };
        };
      };
    };
  };

  "/api/v1/auth/logout": {
    post: {
      responses: {
        200: {
          content: {
            "application/json": { ok: boolean };
          };
        };
      };
    };
  };

  "/api/v1/licitaciones": {
    get: {
      parameters: {
        query?: {
          q?: string;
          estado?: string;
          ccaa?: string;
          tecnologia?: string;
          fecha_desde?: string;
          fecha_hasta?: string;
          importe_min?: number;
          importe_max?: number;
          sort_by?: string;
          sort_order?: "asc" | "desc";
          limit?: number;
          offset?: number;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": {
              items: LicitacionSummary[];
              total: number;
              limit: number;
              offset: number;
            };
          };
        };
      };
    };
  };

  "/api/v1/licitaciones/{id_externo}": {
    get: {
      parameters: {
        path: {
          id_externo: string;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": LicitacionDetail;
          };
        };
        404: {
          content: {
            "application/json": { detail: string };
          };
        };
      };
    };
  };

  "/api/v1/meta/filters": {
    get: {
      responses: {
        200: {
          content: {
            "application/json": {
              estados: string[];
              ccaas: string[];
              tecnologias: string[];
              cpvs: string[];
            };
          };
        };
      };
    };
  };

  "/api/v1/analytics/overview": {
    get: {
      parameters: {
        query?: {
          fecha_desde?: string;
          fecha_hasta?: string;
          ccaa?: string;
          tecnologia?: string;
          estado?: string;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": AnalyticsOverview;
          };
        };
      };
    };
  };

  "/api/v1/analytics/trends": {
    get: {
      parameters: {
        query?: {
          fecha_desde?: string;
          fecha_hasta?: string;
          ccaa?: string;
          tecnologia?: string;
          group_by?: "month" | "week";
        };
      };
      responses: {
        200: {
          content: {
            "application/json": TrendsResult;
          };
        };
      };
    };
  };

  "/api/v1/analytics/geography": {
    get: {
      parameters: {
        query?: {
          fecha_desde?: string;
          fecha_hasta?: string;
          tecnologia?: string;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": GeoResult;
          };
        };
      };
    };
  };

  "/api/v1/analytics/competitors": {
    get: {
      parameters: {
        query?: {
          fecha_desde?: string;
          fecha_hasta?: string;
          ccaa?: string;
          limit?: number;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": CompetitorResult;
          };
        };
      };
    };
  };

  "/api/v1/analytics/scoring": {
    get: {
      parameters: {
        query?: {
          min_score?: number;
          limit?: number;
          band?: string;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": ScoringResult;
          };
        };
      };
    };
  };

  "/api/v1/analytics/quality": {
    get: {
      responses: {
        200: {
          content: {
            "application/json": QualityResult;
          };
        };
      };
    };
  };

  "/api/v1/analytics/organos": {
    get: {
      parameters: {
        query?: {
          fecha_desde?: string;
          fecha_hasta?: string;
          ccaa?: string;
          tecnologia?: string;
          limit?: number;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": OrganosResult;
          };
        };
      };
    };
  };

  "/api/v1/analytics/tecnologias": {
    get: {
      parameters: {
        query?: {
          fecha_desde?: string;
          fecha_hasta?: string;
          ccaa?: string;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": TecnologiasResult;
          };
        };
      };
    };
  };

  "/api/v1/analytics/proyectos-modulos": {
    get: {
      parameters: {
        query?: {
          fecha_desde?: string;
          fecha_hasta?: string;
          tecnologia?: string;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": ProyectosModulosResult;
          };
        };
      };
    };
  };

  "/api/v1/analytics/pipeline": {
    get: {
      parameters: {
        query?: {
          dias?: number;
          limit?: number;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": PipelineResult;
          };
        };
      };
    };
  };

  // ── Resumen endpoints ───────────────────────────────────────────────────

  "/api/v1/analytics/resumen/novedades": {
    get: {
      responses: {
        200: {
          content: {
            "application/json": ResumenNovedadesResult;
          };
        };
      };
    };
  };

  "/api/v1/analytics/resumen/hoy": {
    get: {
      parameters: {
        query?: {
          fecha_desde?: string;
          fecha_hasta?: string;
          ccaa?: string;
          tecnologia?: string;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": ResumenHoyResult;
          };
        };
      };
    };
  };

  "/api/v1/analytics/resumen/timeline": {
    get: {
      parameters: {
        query?: {
          fecha_desde?: string;
          fecha_hasta?: string;
          ccaa?: string;
          tecnologia?: string;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": TimelineScatterResult;
          };
        };
      };
    };
  };

  "/api/v1/analytics/resumen/sankey": {
    get: {
      parameters: {
        query?: {
          fecha_desde?: string;
          fecha_hasta?: string;
          ccaa?: string;
          tecnologia?: string;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": SankeyResult;
          };
        };
      };
    };
  };

  "/api/v1/analytics/resumen/top": {
    get: {
      parameters: {
        query?: {
          fecha_desde?: string;
          fecha_hasta?: string;
          ccaa?: string;
          tecnologia?: string;
          n?: number;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": TopLicitacionesResult;
          };
        };
      };
    };
  };

  // ── Forecast endpoints ──────────────────────────────────────────────────

  "/api/v1/analytics/forecast/volume": {
    get: {
      parameters: {
        query?: {
          months_ahead?: number;
          metric?: string;
          fecha_desde?: string;
          fecha_hasta?: string;
          ccaa?: string;
          tecnologia?: string;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": ForecastVolumeResult;
          };
        };
      };
    };
  };

  "/api/v1/analytics/forecast/retendering": {
    get: {
      parameters: {
        query?: {
          meses_anticipacion?: number;
          solo_mantenimiento?: boolean;
          horizonte_dias?: number;
          fecha_desde?: string;
          fecha_hasta?: string;
          ccaa?: string;
          tecnologia?: string;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": RetenderingResult;
          };
        };
      };
    };
  };

  // ── Trends CPV endpoint ─────────────────────────────────────────────────

  "/api/v1/analytics/trends-cpv": {
    get: {
      parameters: {
        query?: {
          cpv?: string;
          fecha_desde?: string;
          fecha_hasta?: string;
          ccaa?: string;
          tecnologia?: string;
          top_n?: number;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": TrendsCpvResult;
          };
        };
      };
    };
  };

  // ── Organo detail endpoint ──────────────────────────────────────────────

  "/api/v1/analytics/organos/{organo}": {
    get: {
      parameters: {
        path: {
          organo: string;
        };
        query?: {
          fecha_desde?: string;
          fecha_hasta?: string;
          ccaa?: string;
          tecnologia?: string;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": OrganoDetailResult;
          };
        };
      };
    };
  };

  // ── UTEs endpoint ───────────────────────────────────────────────────────

  "/api/v1/analytics/utes": {
    get: {
      parameters: {
        query?: {
          fecha_desde?: string;
          fecha_hasta?: string;
          ccaa?: string;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": UTEResult;
          };
        };
      };
    };
  };

  // ── Compare periods endpoint ────────────────────────────────────────────

  "/api/v1/analytics/compare-periods": {
    get: {
      parameters: {
        query: {
          range_a_desde: string;
          range_a_hasta: string;
          range_b_desde: string;
          range_b_hasta: string;
          ccaa?: string;
          tecnologia?: string;
        };
      };
      responses: {
        200: {
          content: {
            "application/json": CompareResult;
          };
        };
      };
    };
  };

  // ── Search & Ask endpoints ──────────────────────────────────────────────

  "/api/v1/search": {
    post: {
      requestBody: {
        content: {
          "application/json": {
            question: string;
            top_k?: number;
          };
        };
      };
      responses: {
        200: {
          content: {
            "application/json": {
              results: SearchResult[];
              answer?: string;
            };
          };
        };
      };
    };
  };

  "/api/v1/ask": {
    post: {
      requestBody: {
        content: {
          "application/json": {
            question: string;
            top_k?: number;
          };
        };
      };
      responses: {
        200: {
          content: {
            "application/json": {
              answer: string;
              sources: SearchResult[];
            };
          };
        };
      };
    };
  };

  "/api/v1/ask/models": {
    get: {
      responses: {
        200: {
          content: {
            "application/json": { models: string[] };
          };
        };
      };
    };
  };

  // ── Feedback endpoints ──────────────────────────────────────────────────

  "/api/v1/feedback": {
    post: {
      requestBody: {
        content: {
          "application/json": {
            id_externo: string;
            rating: number;
            comment?: string;
          };
        };
      };
      responses: {
        200: {
          content: {
            "application/json": { ok: boolean };
          };
        };
      };
    };
  };

  "/api/v1/feedback/stats": {
    get: {
      responses: {
        200: {
          content: {
            "application/json": {
              total: number;
              avg_rating: number | null;
              by_rating: Record<string, number>;
            };
          };
        };
      };
    };
  };

  "/api/v1/feedback/queue": {
    get: {
      responses: {
        200: {
          content: {
            "application/json": {
              items: {
                id: number;
                id_externo: string;
                rating: number;
                comment: string | null;
                created_at: string;
              }[];
            };
          };
        };
      };
    };
  };

  // ── API keys endpoints ──────────────────────────────────────────────────

  "/api/v1/me/keys": {
    get: {
      responses: {
        200: {
          content: {
            "application/json": {
              keys: {
                id: number;
                prefix: string;
                created_at: string;
                last_used_at: string | null;
              }[];
            };
          };
        };
      };
    };
  };

  "/api/v1/me/keys/rotate": {
    post: {
      responses: {
        200: {
          content: {
            "application/json": {
              key: string;
              prefix: string;
            };
          };
        };
      };
    };
  };

  // ── Exports endpoint ────────────────────────────────────────────────────

  "/api/v1/exports": {
    post: {
      requestBody: {
        content: {
          "application/json": {
            format: "pdf" | "excel" | "csv";
            filters?: Record<string, string>;
          };
        };
      };
      responses: {
        202: {
          content: {
            "application/json": {
              job_id: string;
              status: string;
            };
          };
        };
      };
    };
  };
}

// ── Shared types ──────────────────────────────────────────────────────────

export interface LicitacionSummary {
  id_externo: string;
  titulo: string | null;
  organo_contratacion: string | null;
  importe: number | null;
  estado: string | null;
  fecha_publicacion: string | null;
  ccaa: string | null;
  cpv: string | null;
  url: string | null;
  tecnologia: string | null;
}

export interface LicitacionDetail extends LicitacionSummary {
  descripcion: string | null;
  tipo_contrato: string | null;
  moneda: string | null;
  provincia: string | null;
  duracion_valor: number | null;
  duracion_unidad: string | null;
  fecha_limite: string | null;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  fecha_extraccion: string | null;
  nuts_code: string | null;
}

export interface AnalyticsOverview {
  total_licitaciones: number;
  importe_total: number;
  importe_medio: number;
  organos_unicos: number;
  yoy_delta: number;
  licitaciones_30d: number;
  importe_30d: number;
  por_estado: { estado: string; n: number }[];
  por_mes: { mes: string; n_licitaciones: number; importe: number }[];
  top_organos: {
    organo_contratacion: string;
    n: number;
    importe: number;
  }[];
  funnel_estados: { estado: string; n: number; pct: number }[];
  hhi: number;
  pct_oferta_unica: number;
  // Market indicators (extended)
  pct_pyme: number;
  concentracion_top10: number;
  lead_time_medio: number | null;
  tasa_anulacion: number;
  concentracion_geo_top3: number;
  // "Para hoy" counts (extended)
  calientes_hoy: number;
  vencen_48h: number;
  nuevas_24h: number;
}

export interface TrendPoint {
  period: string;
  count: number;
  importe: number;
}

export interface HeatmapCell {
  row: string;
  col: string;
  value: number;
}

export interface WaterfallPoint {
  period: string;
  delta: number;
  cumulative: number;
}

export interface HistogramBin {
  bin_label: string;
  count: number;
}

export interface TrendsResult {
  series: TrendPoint[];
  heatmap: HeatmapCell[];
  yoy_count: number;
  yoy_importe: number;
  waterfall: WaterfallPoint[];
  histogram_bins: HistogramBin[];
  mes_pico: Record<string, any> | null;
}

export interface GeoEntry {
  ccaa: string;
  count: number;
  importe: number;
  pct: number;
}

export interface GeoResult {
  by_ccaa: GeoEntry[];
  concentracion_top3: number;
  ccaa_mas_activa: string | null;
}

export interface CompetitorEntry {
  nombre: string;
  count: number;
  importe: number;
  cuota: number;
  nif: string | null;
  contratos_por_anio: number;
  importe_medio: number;
  baja_media: number | null;
}

export interface ScatterPoint {
  nombre: string;
  ticket_medio: number;
  n_organos: number;
}

export interface HeatmapCcaaCell {
  ccaa: string;
  empresa: string;
  count: number;
}

export interface CompetitorResult {
  competitors: CompetitorEntry[];
  hhi: number;
  pct_oferta_unica: number;
  total_adjudicaciones: number;
  scatter_data: ScatterPoint[];
  heatmap_ccaa: HeatmapCcaaCell[];
}

export interface ScoredOpportunity {
  id_externo: string;
  titulo: string | null;
  organo_contratacion: string | null;
  importe: number | null;
  score: number;
  band: string;
  risk_flags: string[];
  desglose: Record<string, number>;
}

export interface ScoringResult {
  opportunities: ScoredOpportunity[];
  total_scored: number;
}

export interface ColumnCompleteness {
  columna: string;
  pct: number;
}

export interface QualityResult {
  total_records: number;
  pct_cpv: number;
  pct_importe: number;
  pct_fecha: number;
  pct_titulo: number;
  last_scrape_hours_ago: number | null;
  dlq_count: number;
  completitud_columnas: ColumnCompleteness[];
  cobertura_nif: number;
  cobertura_modulo_sap: number;
}

// ── Mercado analytics types ──────────────────────────────────────────────

export interface OrganoEntry {
  organo_contratacion: string;
  count: number;
  importe: number;
  pct: number;
  ccaa: string | null;
}

export interface OrganosResult {
  organos: OrganoEntry[];
  total_organos: number;
  concentracion_top10: number;
}

export interface TecnologiaEntry {
  tecnologia: string;
  count: number;
  importe: number;
  pct: number;
}

export interface TecnologiasResult {
  tecnologias: TecnologiaEntry[];
  sin_clasificar: number;
}

export interface ModuloEntry {
  modulo: string;
  count: number;
  importe: number;
}

export interface ProyectoTipoEntry {
  tipo: string;
  count: number;
  importe: number;
}

export interface ProyectosModulosResult {
  modulos: ModuloEntry[];
  tipos_proyecto: ProyectoTipoEntry[];
  total_clasificados: number;
}

export interface PipelineEntry {
  id_externo: string;
  titulo: string | null;
  organo_contratacion: string | null;
  importe: number | null;
  fecha_limite: string | null;
  dias_restantes: number;
  estado: string | null;
  score: number | null;
}

export interface HorizonteCount {
  horizonte: string;
  count: number;
  importe: number;
}

export interface TrimestreCount {
  trimestre: string;
  count: number;
  importe: number;
}

export interface UrgenciaValorPoint {
  id_externo: string;
  titulo: string | null;
  dias_restantes: number;
  importe: number;
  es_urgente: boolean;
}

export interface PipelineResult {
  upcoming: PipelineEntry[];
  total_en_plazo: number;
  vencen_7d: number;
  vencen_30d: number;
  por_horizonte: HorizonteCount[];
  por_trimestre: TrimestreCount[];
  urgencia_valor: UrgenciaValorPoint[];
}

// ── Resumen types ─────────────────────────────────────────────────────────

export interface ResumenNovedadesSample {
  id_externo: string;
  titulo: string | null;
  importe: number | null;
  organo_contratacion: string | null;
}

export interface ResumenNovedadesResult {
  count: number;
  sample: ResumenNovedadesSample[];
}

export interface ResumenHoyResult {
  calientes: number;
  vencen_48h: number;
  nuevas_24h: number;
  total_activas: number;
}

export interface TimelineScatterItem {
  id_externo: string;
  titulo: string | null;
  importe: number | null;
  fecha_publicacion: string | null;
  estado: string | null;
}

export interface TimelineScatterResult {
  items: TimelineScatterItem[];
}

export interface SankeyNode {
  id: string;
  label: string;
}

export interface SankeyLink {
  source: string;
  target: string;
  value: number;
}

export interface SankeyResult {
  nodes: SankeyNode[];
  links: SankeyLink[];
}

export interface TopLicitacionItem {
  id_externo: string;
  titulo: string | null;
  organo_contratacion: string | null;
  importe: number | null;
  estado: string | null;
  adjudicatario: string | null;
  baja_pct: number | null;
}

export interface TopLicitacionesResult {
  items: TopLicitacionItem[];
}

// ── Forecast types ────────────────────────────────────────────────────────

export interface ForecastSeriesPoint {
  mes: string;
  valor: number;
  tipo: string;
  lower: number | null;
  upper: number | null;
}

export interface ForecastVolumeResult {
  series: ForecastSeriesPoint[];
}

export interface ForecastEntry {
  id_externo: string;
  titulo: string | null;
  organo_contratacion: string | null;
  importe: number | null;
  fecha_fin_estimada: string | null;
  dias_hasta_fin: number | null;
  estado_forecast: string | null;
  adjudicatarios: string | null;
  baja_pct: number | null;
}

export interface RetenderingResumen {
  ya_vencido: number;
  menos_3m: number;
  tres_seis_m: number;
  seis_doce_m: number;
  mas_doce_m: number;
}

export interface RetenderingResult {
  forecast_entries: ForecastEntry[];
  resumen: RetenderingResumen;
}

// ── Trends CPV types ──────────────────────────────────────────────────────

export interface CpvSeriesPoint {
  period: string;
  count: number;
  importe: number;
}

export interface CpvSeries {
  cpv: string;
  label: string;
  series: CpvSeriesPoint[];
}

export interface CpvImporteRank {
  cpv: string;
  importe_total: number;
  count: number;
}

export interface CpvSummary {
  total_cpvs: number;
  periodo_inicio: string | null;
  periodo_fin: string | null;
}

export interface TrendsCpvResult {
  series_by_cpv: CpvSeries[];
  top_cpv_by_importe: CpvImporteRank[];
  summary: CpvSummary;
}

// ── Organo detail types ───────────────────────────────────────────────────

export interface OrganoKpis {
  total_licitaciones: number;
  importe_total: number;
  pct_adjudicado: number;
  lead_time_medio: number | null;
}

export interface TopAdjudicatario {
  nombre: string;
  count: number;
  importe: number;
}

export interface Estacionalidad {
  mes_numero: number;
  count: number;
}

export interface TopScored {
  id_externo: string;
  titulo: string | null;
  importe: number | null;
  score: number;
}

export interface OrganoDetailResult {
  kpis: OrganoKpis;
  top_adjudicatarios: TopAdjudicatario[];
  estacionalidad: Estacionalidad[];
  top_scored: TopScored[];
}

// ── UTE types ─────────────────────────────────────────────────────────────

export interface UTEKpis {
  total_ute: number;
  importe_ute: number;
  ticket_medio_ute: number;
  ticket_medio_individual: number;
  empresas_distintas: number;
}

export interface UTEMiembro {
  nombre: string;
  count: number;
  importe: number;
}

export interface UTEEvolucion {
  period: string;
  contratos: number;
  importe: number;
}

export interface UTETablaComparativa {
  count: number;
  importe_medio: number;
  importe_total: number;
}

export interface UTEComparacion {
  ute: UTETablaComparativa;
  individual: UTETablaComparativa;
}

export interface UTEResult {
  kpis: UTEKpis;
  top_miembros: UTEMiembro[];
  evolucion: UTEEvolucion[];
  tabla_comparativa: UTEComparacion;
}

// ── Compare periods types ─────────────────────────────────────────────────

export interface PeriodStats {
  total: number;
  importe_total: number;
  importe_medio: number;
  organos: number;
}

export interface PeriodDeltas {
  total_pct: number;
  importe_total_pct: number;
  importe_medio_pct: number;
  organos_pct: number;
}

export interface CompareResult {
  period_a: PeriodStats;
  period_b: PeriodStats;
  deltas: PeriodDeltas;
}

// ── Search & Export types ────────────────────────────────────────────────

export interface SearchResult {
  id_externo: string;
  titulo: string | null;
  organo_contratacion: string | null;
  importe: number | null;
  score: number;
  source: string;
}
