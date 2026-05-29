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

export interface TrendsResult {
  series: TrendPoint[];
  heatmap: HeatmapCell[];
  yoy_count: number;
  yoy_importe: number;
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
}

export interface CompetitorResult {
  competitors: CompetitorEntry[];
  hhi: number;
  pct_oferta_unica: number;
  total_adjudicaciones: number;
}

export interface ScoredOpportunity {
  id_externo: string;
  titulo: string | null;
  organo_contratacion: string | null;
  importe: number | null;
  score: number;
  band: string;
  risk_flags: string[];
}

export interface ScoringResult {
  opportunities: ScoredOpportunity[];
  total_scored: number;
}

export interface QualityResult {
  total_records: number;
  pct_cpv: number;
  pct_importe: number;
  pct_fecha: number;
  pct_titulo: number;
  last_scrape_hours_ago: number | null;
  dlq_count: number;
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

export interface PipelineResult {
  upcoming: PipelineEntry[];
  total_en_plazo: number;
  vencen_7d: number;
  vencen_30d: number;
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
