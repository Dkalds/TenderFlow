import type { Adjudicatario, Lote } from "@/lib/api-types";

/** Ficha de licitación tal como la consumen /detalle, el inspector y el comparador. */
export interface LicitacionDetail {
  id_externo: string;
  titulo: string | null;
  organo_contratacion: string | null;
  importe: number | null;
  estado: string | null;
  fecha_publicacion: string | null;
  ccaa: string | null;
  cpv: string | null;
  url: string | null;
  /** Fuente de ingesta (`placsp`, `ted`, `pscp`…): rotula `url`. Ver `lib/fuentes`. */
  fuente: string | null;
  tecnologia: string | null;
  tipo_contrato: string | null;
  /** F1.7 — código CODICE crudo; la etiqueta la pone `CodigoLegible`. */
  procedimiento?: string | null;
  tramitacion?: string | null;
  provincia: string | null;
  fecha_limite: string | null;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  descripcion: string | null;
  /*
   * Lo que sigue lo manda solo `GET /licitaciones/{id}`: el comparador
   * construye fichas desde el listado, que no lo trae, y por eso es opcional.
   */
  /** Número de expediente tal como lo publica el órgano (sin prefijo de fuente). */
  expediente?: string | null;
  nuts_code?: string | null;
  /** Duración publicada: `duracion_unidad` es `ANN`, `MON` o `DAY`. */
  duracion_valor?: number | null;
  duracion_unidad?: string | null;
  /** Texto de la fuente sobre prórrogas, tal cual. */
  prorroga_descripcion?: string | null;
  /** ADR-032 §A: `sin_iva`, `con_iva` o `desconocido`; dice qué es `importe`. */
  importe_tipo?: string | null;
  importe_con_iva?: number | null;
  valor_estimado?: number | null;
  fecha_actualizacion_fuente?: string | null;
  /** Lista vacía = lote único implícito, no «sin medir». */
  lotes?: Lote[];
  /**
   * Quién lo ganó, por lote cuando lo hay. Opcional porque el comparador
   * también construye fichas desde el listado, que no lo trae; la ficha de
   * `GET /licitaciones/{id}` lo manda siempre (lista vacía si no hay).
   */
  adjudicatarios?: Adjudicatario[];
  score?: number;
  /** Banda del scoring (`Caliente|Atractiva|Tibia|Descarte`), si ya llegó. */
  band?: string | null;
  score_desglose?: Record<string, number>;
  risk_flags?: string[];
}
