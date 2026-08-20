"use client";

export interface CompanyIdentity {
  empresa_id: number;
  nombre: string;
  nif: string | null;
  es_ute: boolean;
  grupo: string | null;
}

export interface CompanyTotals {
  contratos: number;
  importe_total: number;
  importe_mediano: number | null;
  ofertas_medias: number | null;
  baja_media_pct: number | null;
  pct_oferta_unica: number | null;
  cobertura_ofertas_pct: number;
  primera_adjudicacion: string | null;
  ultima_adjudicacion: string | null;
  organos: number;
  territorios: number;
  familias_cpv: number;
}

export interface CompanyBreakdown {
  codigo: string | null;
  label: string;
  cpv2?: string | null;
  ccaa?: string | null;
  organo?: string | null;
  contratos: number;
  importe: number;
  cuota_empresa_pct: number;
}

export interface CompanyYear {
  anio: number;
  contratos: number;
  importe: number;
}

export interface CompanyPosition {
  rank: number | null;
  empresas: number;
  cuota_pct: number | null;
  importe_segmento: number;
}

export interface CompanyComparison {
  desde: string;
  hasta: string;
  anterior_desde: string;
  anterior_hasta: string;
  contratos: number;
  contratos_anterior: number;
  variacion_contratos_pct: number | null;
  importe: number;
  importe_anterior: number;
  variacion_importe_pct: number | null;
}

export interface CompanyConcentration {
  organo_principal: string | null;
  top1_contratos_pct: number;
  top1_importe_pct: number;
  top3_importe_pct: number;
}

export interface CompanyMovement {
  kind: string;
  tone: "positive" | "neutral" | "warning" | "negative";
  title: string;
  detail: string;
}

export interface CompanyScope {
  fecha_desde: string | null;
  fecha_hasta: string | null;
  cpv: string | null;
  ccaas: string[];
  tecnologias: string[];
  importe_min: number | null;
}

export interface CompanyHistory {
  contratos: number;
  importe_total: number;
  primera_adjudicacion: string | null;
  ultima_adjudicacion: string | null;
}

/**
 * UTE en la que la empresa participa como miembro (`CompetitiveCompanyUteParticipationDTO`).
 *
 * `contratos` e `importe_total` son de la UTE, no de la empresa: el backend
 * mantiene esta lista deliberadamente fuera de `totales`/`posicion_mercado`,
 * que solo cuentan lo adjudicado directamente a `empresa_id`. La UTE ya figura
 * como empresa propia en la cuota de mercado, así que sumar estos importes a
 * los totales del dossier contaría el mismo dinero dos veces.
 */
export interface CompanyUteParticipation {
  ute_empresa_id: number;
  ute_nombre: string;
  otros_miembros: string[];
  contratos: number;
  importe_total: number;
}

export interface CompanyProfileData {
  empresa: CompanyIdentity;
  scope: CompanyScope;
  actividad_historica: CompanyHistory;
  totales: CompanyTotals;
  posicion_mercado: CompanyPosition;
  comparacion: CompanyComparison;
  concentracion_clientes: CompanyConcentration;
  por_cpv: CompanyBreakdown[];
  por_ccaa: CompanyBreakdown[];
  organos_principales: CompanyBreakdown[];
  por_anio: CompanyYear[];
  movimientos: CompanyMovement[];
  participaciones_ute: CompanyUteParticipation[];
}

export interface CompanyAward {
  licitacion_id: string;
  titulo: string | null;
  organo_contratacion: string | null;
  fecha_adjudicacion: string | null;
  cpv: string | null;
  ccaa: string | null;
  tecnologia: string | null;
  presupuesto_licitacion: number | null;
  importe_adjudicado: number | null;
  baja_pct: number | null;
  n_ofertas_recibidas: number | null;
}

export interface CompanyAwardsData {
  items: CompanyAward[];
  total: number;
  limit: number;
  offset: number;
}

const CPV_FAMILY_LABELS: Record<string, string> = {
  "30": "Equipamiento informático y oficina",
  "32": "Telecomunicaciones y electrónica",
  "48": "Software y sistemas de información",
  "50": "Mantenimiento y reparación",
  "64": "Servicios de telecomunicaciones",
  "71": "Arquitectura, ingeniería e inspección",
  "72": "Servicios TI y consultoría tecnológica",
  "73": "Investigación y desarrollo",
  "79": "Consultoría y servicios empresariales",
  "80": "Formación y educación",
  "85": "Servicios sanitarios y sociales",
};

export function cpvFamilyLabel(code: string | null | undefined): string {
  if (!code) return "Familia CPV sin identificar";
  return CPV_FAMILY_LABELS[code] ?? `Familia CPV ${code}`;
}

export function buildExecutiveSummary(profile: CompanyProfileData): string {
  const parts: string[] = [];
  const topCpv = profile.por_cpv[0];
  const topRegion = profile.por_ccaa[0];
  const concentration = profile.concentracion_clientes;
  const delta = profile.comparacion.variacion_importe_pct;

  if (topCpv) {
    parts.push(
      `Su actividad se concentra en ${cpvFamilyLabel(topCpv.codigo)} (${topCpv.cuota_empresa_pct.toFixed(0)}% del importe)`,
    );
  }
  if (topRegion) {
    parts.push(`opera principalmente en ${topRegion.label} (${topRegion.cuota_empresa_pct.toFixed(0)}%)`);
  }
  if (concentration.organo_principal) {
    parts.push(
      `y su principal cliente es ${concentration.organo_principal} (${concentration.top1_importe_pct.toFixed(0)}% del importe)`,
    );
  }
  if (delta != null) {
    parts.push(
      `El volumen adjudicado ${delta >= 0 ? "crece" : "retrocede"} un ${Math.abs(delta).toFixed(1)}% frente al periodo comparable`,
    );
  }

  if (parts.length === 0) {
    return "Todavía no hay suficiente cobertura para describir la operativa de esta empresa.";
  }
  return `${parts.join("; ")}.`;
}
