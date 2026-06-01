import type { AnalyticsOverview } from "@/generated/api";

export interface TimelineItem {
  id_externo: string;
  titulo: string;
  importe: number | null;
  fecha_publicacion: string;
  estado: string;
  organo_contratacion: string | null;
  tipo_contrato: string | null;
  ccaa: string | null;
}

export interface CompareResponse {
  period_a: Record<string, number>;
  period_b: Record<string, number>;
  deltas: Record<string, number>;
}

export type ExtendedOverview = AnalyticsOverview;

export const ITEMS_PER_PAGE = 10;
