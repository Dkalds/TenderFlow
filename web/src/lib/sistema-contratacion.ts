import type { Schemas } from "@/lib/api-types";

/** `licitaciones.sistema_contratacion`: los valores de `shared/sistema_contratacion.py`. */
export type SistemaContratacion = NonNullable<Schemas["LicitacionDetail"]["sistema_contratacion"]>;

/** Los que la ficha y Renovaciones rotulan; `ninguno` no se pinta. */
export type SistemaRotulado = Exclude<SistemaContratacion, "ninguno">;

export const ETIQUETA_SISTEMA: Record<SistemaRotulado, string> = {
  marco: "Acuerdo marco",
  sda: "Sistema dinámico de adquisición",
  basado_marco: "Contrato basado en un acuerdo marco",
  basado_sda: "Contrato basado en un sistema dinámico",
};

/** `null` para «ninguno» y para lo que la fuente no dice. */
export function sistemaRotulado(sistema: SistemaContratacion | null | undefined): SistemaRotulado | null {
  return sistema && sistema !== "ninguno" ? sistema : null;
}

/** Un marco o un SDA: admite empresas y de él cuelgan contratos basados. */
export function esMarco(sistema: SistemaContratacion | null | undefined): sistema is "marco" | "sda" {
  return sistema === "marco" || sistema === "sda";
}
