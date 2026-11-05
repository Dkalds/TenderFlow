"use client";

import type { Schemas } from "@/lib/api-types";
import { formatPercent } from "@/lib/utils";

/*
 * El dossier de `GET /competitive/empresas/{empresa_id}/perfil`, con las
 * formas del esquema generado. Hasta 2026-11 eran interfaces escritas a mano
 * que daban por presentes listas que la API declara opcionales.
 */
export type CompanyProfileData = Schemas["CompetitiveCompanyProfileDTO"];
export type CompanyIdentity = Schemas["CompetitiveCompanyIdentityDTO"];
export type CompanyTotals = Schemas["CompetitiveCompanyTotalsDTO"];
export type CompanyBreakdown = Schemas["CompetitiveCompanyBreakdownDTO"];
export type CompanyYear = Schemas["CompetitiveCompanyYearDTO"];
export type CompanyPosition = Schemas["CompetitiveCompanyPositionDTO"];
export type CompanyComparison = Schemas["CompetitiveCompanyComparisonDTO"];
export type CompanyConcentration = Schemas["CompetitiveCompanyConcentrationDTO"];
export type CompanyMovement = Schemas["CompetitiveCompanySignalDTO"];
export type CompanyScope = Schemas["CompetitiveCompanyScopeDTO"];
export type CompanyHistory = Schemas["CompetitiveCompanyHistoryDTO"];

/**
 * UTE en la que la empresa participa como miembro (`CompetitiveCompanyUteParticipationDTO`).
 *
 * `contratos` e `importe_total` son de la UTE, no de la empresa: el backend
 * mantiene esta lista deliberadamente fuera de `totales`/`posicion_mercado`,
 * que solo cuentan lo adjudicado directamente a `empresa_id`. La UTE ya figura
 * como empresa propia en la cuota de mercado, así que sumar estos importes a
 * los totales del dossier contaría el mismo dinero dos veces.
 */
export type CompanyUteParticipation = Schemas["CompetitiveCompanyUteParticipationDTO"];

/** Celda de un corte F3.5: `baja_media` en tanto por uno, nula bajo el mínimo. */
export type CompanyCorte = Schemas["CompetitiveCompanyCorteDTO"];

/** Media de puntos de precio y técnicos por acta; cada media, nula bajo `min_actas`. */
export type CompanyActaScores = Schemas["CompetitiveCompanyActaScoresDTO"];

/** Puntos porcentuales de diferencia a partir de los que una media pesa claramente más. */
const DIFERENCIA_CLARA_ACTAS = 15;

/**
 * Lee las dos medias que da el backend; no calcula ninguna. Solo con las dos
 * publicadas: con una sola no hay con qué comparar.
 */
export function lecturaActas(acta: CompanyActaScores): string | null {
  const precio = acta.precio.pct_medio;
  const tecnica = acta.tecnica.pct_medio;
  if (precio == null || tecnica == null) return null;
  if (precio - tecnica >= DIFERENCIA_CLARA_ACTAS) {
    return "Puntúa más en precio que en lo técnico: compite sobre todo con la oferta económica.";
  }
  if (tecnica - precio >= DIFERENCIA_CLARA_ACTAS) {
    return "Puntúa más en lo técnico que en precio: compite sobre todo con la propuesta técnica.";
  }
  return "Puntúa parecido en precio y en lo técnico.";
}

export type CompanyAward = Schemas["CompetitiveCompanyAwardDTO"];
export type CompanyAwardsData = Schemas["CompetitiveCompanyAwardsDTO"];

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

/**
 * La variación frente al periodo anterior, en neutro: que un competidor crezca
 * no es ni bueno ni malo para quien mira, así que no lleva verde ni rojo. Sin
 * variación, el detalle de la cifra.
 */
export function variacionFrenteAnterior(delta: number | null | undefined, detalle: string): string {
  if (delta == null) return detalle;
  return `${delta >= 0 ? "+" : ""}${formatPercent(delta)} frente al periodo anterior`;
}

export function buildExecutiveSummary(profile: CompanyProfileData): string {
  const parts: string[] = [];
  const topCpv = profile.por_cpv?.[0];
  const topRegion = profile.por_ccaa?.[0];
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
      `El volumen adjudicado ${delta >= 0 ? "crece" : "retrocede"} un ${formatPercent(Math.abs(delta))} frente al periodo comparable`,
    );
  }

  if (parts.length === 0) {
    return "Todavía no hay suficiente cobertura para describir la operativa de esta empresa.";
  }
  return `${parts.join("; ")}.`;
}
