/**
 * Los filtros del tablero y su traducción a `GET /pursuits` (CU-28).
 *
 * Se filtra **en servidor**. El tablero pedía la página por defecto —cincuenta—
 * y filtraba esas cincuenta en el navegador: la oportunidad que no había
 * llegado no aparecía por mucho que se buscara. Ahora cada control es un
 * parámetro del listado y el `total` que responde es el del conjunto filtrado.
 */
import { TODAS_LAS_ETIQUETAS } from "@/components/etiquetas/filtro-etiqueta";
import type { PursuitFilters, PursuitPlazo } from "@/hooks/use-pursuits";

/** Valor del selector de responsable que no filtra. */
export const TODOS_LOS_RESPONSABLES = "todos";

/**
 * Cuántas oportunidades pide el tablero. Doscientas caben en seis columnas y
 * son las que acepta de una vez `POST /etiquetas/por-objeto`, que pinta los
 * chips de cada tarjeta. Por encima, el tablero dice que es parcial y pide
 * acotar con los filtros, en vez de contar como «todas» las que caben.
 */
export const TOPE_TABLERO = 200;

export interface FiltrosTablero {
  q: string;
  /** Id de la etiqueta, o `TODAS_LAS_ETIQUETAS`. */
  etiqueta: string;
  /** Id del responsable, o `TODOS_LOS_RESPONSABLES`. */
  responsable: string;
  plazo: PursuitPlazo | "todos";
}

export const FILTROS_VACIOS: FiltrosTablero = {
  q: "",
  etiqueta: TODAS_LAS_ETIQUETAS,
  responsable: TODOS_LOS_RESPONSABLES,
  plazo: "todos",
};

/**
 * Las opciones de plazo, con el rótulo que ve quien filtra. El plazo es el de
 * presentación y el servidor solo lo cuenta en oportunidades abiertas y sin
 * presentar (lo dice la pista del tablero cuando el filtro está puesto).
 */
export const PLAZOS: { value: FiltrosTablero["plazo"]; label: string }[] = [
  { value: "todos", label: "Cualquier plazo" },
  { value: "vencido", label: "Plazo vencido" },
  { value: "7d", label: "Vence en 7 días" },
  { value: "30d", label: "Vence en 30 días" },
];

export function hayFiltros(filtros: FiltrosTablero): boolean {
  return (
    filtros.q.trim() !== "" ||
    filtros.etiqueta !== TODAS_LAS_ETIQUETAS ||
    filtros.responsable !== TODOS_LOS_RESPONSABLES ||
    filtros.plazo !== "todos"
  );
}

/** Los parámetros de `GET /pursuits` para estos filtros. Lo que no filtra no viaja. */
export function consultaDelTablero(filtros: FiltrosTablero): PursuitFilters {
  const consulta: PursuitFilters = { limit: TOPE_TABLERO };
  const texto = filtros.q.trim();
  if (texto) consulta.q = texto;
  if (filtros.etiqueta !== TODAS_LAS_ETIQUETAS) consulta.etiqueta = Number(filtros.etiqueta);
  if (filtros.responsable !== TODOS_LOS_RESPONSABLES) consulta.responsible_user_id = Number(filtros.responsable);
  if (filtros.plazo !== "todos") consulta.plazo = filtros.plazo;
  return consulta;
}
