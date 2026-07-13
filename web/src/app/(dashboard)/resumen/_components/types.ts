import type { AnalyticsOverview } from "@/lib/api-types";

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

export type ExtendedOverview = AnalyticsOverview;

export const ITEMS_PER_PAGE = 10;
