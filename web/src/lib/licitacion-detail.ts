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
  score?: number;
  /** Banda del scoring (`Caliente|Atractiva|Tibia|Descarte`), si ya llegó. */
  band?: string | null;
  score_desglose?: Record<string, number>;
  risk_flags?: string[];
}
