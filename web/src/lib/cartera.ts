/**
 * F4.3 — lógica de la vista Cartera, fuera del componente para poder
 * probarla sin montar nada.
 *
 * El endpoint devuelve la cartera **entera** de la organización (una fila por
 * contrato ganado, decenas como mucho), así que los filtros por tecnología y
 * órgano se aplican aquí sobre el universo completo: no hay paginación que
 * haga que el recorte en cliente mienta sobre lo que no se ve.
 */
import type { Schemas } from "@/lib/api-types";

export type ContratoCartera = Schemas["ContratoCartera"];

export interface FiltrosCartera {
  tecnologia: string | null;
  organo: string | null;
}

/** Las tecnologías vienen como CSV en la columna (`"SAP,Oracle"`). */
export function tecnologiasDe(contrato: ContratoCartera): string[] {
  return (contrato.tecnologia ?? "")
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

export function opcionesCartera(contratos: readonly ContratoCartera[]): {
  tecnologias: string[];
  organos: string[];
} {
  const tecnologias = new Set<string>();
  const organos = new Set<string>();
  for (const contrato of contratos) {
    for (const t of tecnologiasDe(contrato)) tecnologias.add(t);
    if (contrato.organo_contratacion) organos.add(contrato.organo_contratacion);
  }
  const orden = (a: string, b: string) => a.localeCompare(b, "es");
  return { tecnologias: [...tecnologias].sort(orden), organos: [...organos].sort(orden) };
}

export function filtrarCartera(
  contratos: readonly ContratoCartera[],
  filtros: FiltrosCartera,
): ContratoCartera[] {
  return contratos.filter(
    (contrato) =>
      (!filtros.tecnologia || tecnologiasDe(contrato).includes(filtros.tecnologia)) &&
      (!filtros.organo || contrato.organo_contratacion === filtros.organo),
  );
}

/**
 * Cuánto falta, en palabras. `null` en `meses_restantes` es «sin fecha de
 * fin», y se dice así: el backend no inventa un año por defecto y la pantalla
 * tampoco.
 */
export function plazoRestante(contrato: ContratoCartera): string {
  const meses = contrato.meses_restantes;
  if (meses == null) return "Sin fecha de fin";
  if (meses < 0) return "Vencido";
  if (meses === 0) return "Vence este mes";
  if (meses === 1) return "Vence en 1 mes";
  return `Vence en ${meses} meses`;
}

/** Urgencia visual: las ventanas de aviso del backend son 6, 3 y 1 meses. */
export function urgenciaCartera(contrato: ContratoCartera): "vencido" | "pronto" | "normal" | "sin_fecha" {
  const meses = contrato.meses_restantes;
  if (meses == null) return "sin_fecha";
  if (meses < 0) return "vencido";
  return meses <= 6 ? "pronto" : "normal";
}

const ORIGEN_FIN: Record<string, { texto: string; explicacion: string }> = {
  publicada: { texto: "publicada", explicacion: "Fecha de fin publicada por la fuente." },
  duracion: {
    texto: "estimada",
    explicacion: "Calculada con la fecha de inicio y la duración: la fuente no publicó fecha de fin.",
  },
  prorroga: {
    texto: "con prórroga",
    explicacion: "La fecha de fin incluye las prórrogas registradas en los eventos del contrato.",
  },
  manual: { texto: "manual", explicacion: "Fecha de fin introducida por el equipo." },
};

/** De dónde sale la fecha de fin (ADR-014: una estimada no se lee como publicada). */
export function origenFin(origen: string | null | undefined) {
  return origen ? (ORIGEN_FIN[origen] ?? { texto: origen, explicacion: origen }) : null;
}
