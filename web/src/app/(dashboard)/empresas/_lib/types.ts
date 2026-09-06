/**
 * Espejo de las respuestas de `/api/v1/empresas` y `/api/v1/competitive` que
 * consume esta ruta.
 *
 * Viven aquí, y no en cada pieza, para que la tabla, el perfil y la cola de
 * revisión hablen de la misma forma: si el contrato cambia, cambia en un sitio.
 */

export interface EmpresaRow {
  empresa_id: number;
  nombre_canonico: string;
  nif_canonico: string | null;
  es_ute: number;
  es_pyme: number | null;
  grupo: string | null;
  n_adjudicaciones: number;
  importe_total: number;
}

export interface EmpresaStats {
  adjudicaciones_total: number;
  adjudicaciones_enlazadas: number;
  pct_filas: number;
  pct_importe: number;
  empresas: number;
  revisiones_pendientes: number;
}

export interface EmpresaDetail {
  empresa_id: number;
  nombre_canonico: string;
  nif_canonico: string | null;
  es_ute: number;
  grupo: string | null;
  aliases: { alias_normalizado: string; nif_variante: string | null; fuente: string }[];
  ute_miembros: { empresa_id: number; nombre_canonico: string }[];
  participa_en_utes: { empresa_id: number; nombre_canonico: string }[];
}

export interface PerfilEmpresa {
  totales: {
    contratos: number;
    importe_total: number;
    ofertas_medias: number | null;
    primera_adjudicacion: string | null;
    ultima_adjudicacion: string | null;
  };
  por_cpv: { cpv2: string; contratos: number; importe: number }[];
  por_ccaa: { ccaa: string; contratos: number; importe: number }[];
  organos_principales: { organo: string; contratos: number; importe: number }[];
  por_anio?: { anio: number; contratos: number; importe: number }[];
}

export interface ReviewItem {
  id: number;
  nombre_original: string;
  nif: string | null;
  score: number;
  candidato_empresa_id: number | null;
  candidato_nombre: string | null;
  candidato_nif: string | null;
}

/** Fila de cualquiera de los tres desgloses del perfil (CPV, territorio, órgano). */
export interface RankingRow {
  label: string;
  contratos: number;
  importe: number;
}

/** Las dos vistas del maestro: el buscador y la cola de matches dudosos. */
export type VistaMaestro = "maestro" | "revision";
