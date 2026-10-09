"use client";

/**
 * Datos y series de la vista Órganos.
 *
 * Dos peticiones con **el mismo ámbito**: el ranking y el perfil del órgano
 * abierto. Que compartan filtros no es un detalle de implementación — el perfil
 * lleva el nombre del órgano en la cabecera, y responder ahí con el histórico
 * completo mientras el mapa cuenta sólo las SAP es el mismo encabezado sobre
 * dos universos.
 *
 * La tercera, `/analytics/overview`, da el total de licitaciones del ámbito que
 * el titular necesita («10 órganos concentran el 62 % de las 1.284
 * licitaciones»). Es la misma clave que usa la barra de ámbito para su recuento,
 * así que no cuesta una petición más.
 */

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { useDebounce } from "@/hooks/use-debounce";
import { foldText, truncate } from "@/lib/utils";

export type MetricaOrganos = "count" | "importe";

export interface OrganoItem {
  organo_contratacion: string;
  count: number;
  importe: number;
  pct: number;
  ccaa?: string;
}

export interface OrganosResponse {
  organos: OrganoItem[];
  total_organos: number;
  importe_total?: number;
  concentracion_top10?: number;
}

/** Lo que el titular toma de `/analytics/overview`; el resto no se lee. */
interface OverviewTotales {
  total_licitaciones: number;
  importe_medio: number;
}

export interface OrganoKpis {
  total_licitaciones: number;
  importe_total: number;
  importe_medio: number;
  pct_adjudicado: number;
  lead_time_medio: number | null;
  top_adjudicatario: string | null;
  top_adj_importe: number;
}

export interface TopScoredItem {
  id_externo: string;
  titulo: string | null;
  importe: number | null;
  score: number;
  ccaa?: string | null;
  estado?: string | null;
  estado_desc?: string | null;
  banda?: string | null;
  empresa?: string | null;
  baja_pct?: number | null;
  fecha_adjudicacion?: string | null;
  modulos_str?: string | null;
  url?: string | null;
  tipo_proyecto?: string | null;
  tipo_contrato_desc?: string | null;
  cpv_desc?: string | null;
}

export interface Adjudicatario {
  nombre: string;
  count: number;
  importe: number;
}

export interface OrganoDetailResponse {
  kpis: OrganoKpis;
  top_adjudicatarios: Adjudicatario[];
  estacionalidad: { mes_numero: number; count: number }[];
  top_scored: TopScoredItem[];
}

/** Un órgano en el mapa de compradores. */
export interface PuntoOrgano {
  organo: string;
  ccaa?: string;
  count: number;
  importe: number;
  /** Importe medio por licitación: el tamaño del punto. */
  medio: number;
  /** Nombre corto junto al punto, sólo en los que destacan; vacío en el resto. */
  etiqueta: string;
  seleccionado: boolean;
}

/** Una fila del gráfico mariposa: las dos medidas a escala del máximo visible. */
export interface FilaMariposa {
  organo: string;
  ccaa?: string;
  count: number;
  importe: number;
  pctCount: number;
  pctImporte: number;
  seleccionado: boolean;
}

/** Cuántas filas del ranking se pintan en la mariposa. */
export const FILAS_MARIPOSA = 12;

/** Cuántos puntos llevan su nombre al lado, por cada una de las dos medidas. */
const ETIQUETAS_POR_MEDIDA = 6;

function mediana(valores: number[]): number | null {
  if (valores.length < 2) return null;
  const ordenados = [...valores].sort((a, b) => a - b);
  const mitad = Math.floor(ordenados.length / 2);
  return ordenados.length % 2 === 0
    ? (ordenados[mitad - 1] + ordenados[mitad]) / 2
    : ordenados[mitad];
}

export function useOrganosView() {
  const searchParams = useSearchParams();
  // Deep-link externo: `?organo_q=<órgano>` siembra el filtro local. `q`
  // pertenece al ámbito global y useFilteredQuery lo adjunta por separado.
  const [filter, setFilter] = useState(() => searchParams?.get("organo_q") ?? "");
  const [metrica, setMetrica] = useState<MetricaOrganos>("count");
  const [selectedOrgano, setSelectedOrgano] = useState<string | null>(null);
  // El perfil arranca abierto con el primer órgano del ranking; cerrarlo es una
  // decisión aparte de «ninguno elegido», porque sin ella el cierre volvería a
  // abrir el primero.
  const [perfilCerrado, setPerfilCerrado] = useState(false);

  // Búsqueda en la propia API (sin tildes): sin q devuelve solo el top-50 por
  // actividad, así que un órgano fuera de ese ranking jamás aparecería
  // filtrando solo en cliente.
  const debouncedFilter = useDebounce(filter, 300);
  const { data, isLoading, error, refetch } = useFilteredQuery<OrganosResponse>(
    ["analytics", "organos", debouncedFilter],
    "/api/v1/analytics/organos",
    // El error lo pinta la vista en línea (PanelError): sin toast además.
    { staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
    debouncedFilter ? { organo_q: debouncedFilter } : undefined,
  );

  // Misma clave que el recuento de la barra de ámbito (`analyticsKeys.overview`),
  // así que en las pantallas que consumen el ámbito entero comparte caché.
  const { data: overview } = useFilteredQuery<OverviewTotales>(
    ["analytics", "overview"],
    "/api/v1/analytics/overview",
    { staleTime: 60_000, meta: META_ERROR_EN_LINEA },
  );

  const items = useMemo(() => data?.organos ?? [], [data]);

  const filteredItems = useMemo(() => {
    if (!filter) return items;
    const q = foldText(filter);
    return items.filter(
      (i) =>
        foldText(i.organo_contratacion).includes(q) ||
        (i.ccaa && foldText(i.ccaa).includes(q)),
    );
  }, [items, filter]);

  const ordenados = useMemo(() => {
    const valor = metrica === "count" ? (o: OrganoItem) => o.count : (o: OrganoItem) => o.importe;
    return [...filteredItems].sort((a, b) => valor(b) - valor(a));
  }, [filteredItems, metrica]);

  const primero = ordenados[0]?.organo_contratacion ?? null;
  const organoAbierto = perfilCerrado ? null : (selectedOrgano ?? primero);
  const rangoAbierto =
    organoAbierto == null ? null : ordenados.findIndex((o) => o.organo_contratacion === organoAbierto) + 1;

  // El perfil viaja con el mismo ámbito que el mapa del que se abre, y sin
  // `keepPreviousData` (último argumento) a propósito: lleva el nombre del
  // órgano en la cabecera, y servir las cifras del anterior mientras carga el
  // nuevo sería el mismo encabezado sobre dos universos. Se prefiere el esqueleto.
  const {
    data: detailData,
    isLoading: detailLoading,
    error: detailError,
    refetch: refetchDetail,
  } = useFilteredQuery<OrganoDetailResponse>(
    ["analytics", "organo-detail", organoAbierto ?? ""],
    `/api/v1/analytics/organos/${encodeURIComponent(organoAbierto ?? "")}`,
    { enabled: !!organoAbierto, staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
    undefined,
    true,
  );

  const medianas = useMemo(
    () => ({
      count: mediana(filteredItems.map((o) => o.count)),
      importe: mediana(filteredItems.map((o) => o.importe)),
    }),
    [filteredItems],
  );

  const puntos = useMemo<PuntoOrgano[]>(() => {
    const porCount = [...filteredItems].sort((a, b) => b.count - a.count).slice(0, ETIQUETAS_POR_MEDIDA);
    const porImporte = [...filteredItems].sort((a, b) => b.importe - a.importe).slice(0, ETIQUETAS_POR_MEDIDA);
    const conEtiqueta = new Set([...porCount, ...porImporte].map((o) => o.organo_contratacion));
    return filteredItems.map((o) => {
      const seleccionado = o.organo_contratacion === organoAbierto;
      return {
        organo: o.organo_contratacion,
        ccaa: o.ccaa,
        count: o.count,
        importe: o.importe,
        medio: o.count > 0 ? o.importe / o.count : 0,
        etiqueta: seleccionado || conEtiqueta.has(o.organo_contratacion) ? truncate(o.organo_contratacion, 28) : "",
        seleccionado,
      };
    });
  }, [filteredItems, organoAbierto]);

  const mariposa = useMemo<FilaMariposa[]>(() => {
    const filas = ordenados.slice(0, FILAS_MARIPOSA);
    const maxCount = Math.max(1, ...filas.map((o) => o.count));
    const maxImporte = Math.max(1, ...filas.map((o) => o.importe));
    return filas.map((o) => ({
      organo: o.organo_contratacion,
      ccaa: o.ccaa,
      count: o.count,
      importe: o.importe,
      pctCount: (o.count / maxCount) * 100,
      pctImporte: (o.importe / maxImporte) * 100,
      seleccionado: o.organo_contratacion === organoAbierto,
    }));
  }, [ordenados, organoAbierto]);

  // Concentración de los 10 primeros. Por licitaciones es la cifra de la API
  // sobre TODO el ámbito. Por importe no hay cifra de la API: se suma el top-10
  // por importe de la lista recibida (los 50 más activos) contra el importe
  // total del ámbito, y la vista lo dice como parcial.
  const importeTotal = data?.importe_total ?? null;
  const concentracion = useMemo(() => {
    if (metrica === "count") {
      return { pct: data?.concentracion_top10 ?? null, parcial: false };
    }
    if (importeTotal == null || importeTotal <= 0 || ordenados.length === 0) {
      return { pct: null, parcial: true };
    }
    const top10 = ordenados.slice(0, 10).reduce((suma, o) => suma + o.importe, 0);
    return { pct: (top10 / importeTotal) * 100, parcial: true };
  }, [metrica, data, importeTotal, ordenados]);

  return {
    data,
    items,
    filteredItems,
    puntos,
    medianas,
    mariposa,
    concentracion,
    metrica,
    setMetrica,
    // `?? null` y no `?? 0`: un campo que la API no manda no es un cero.
    concentracionTop10: data?.concentracion_top10 ?? null,
    totalLicitaciones: overview?.total_licitaciones ?? null,
    importeMedio: overview?.importe_medio ?? null,
    importeTotal,
    totalOrganos: data?.total_organos ?? null,
    filter,
    setFilter,
    organoAbierto,
    rangoAbierto,
    abrirOrgano: (organo: string) => {
      setSelectedOrgano(organo);
      setPerfilCerrado(false);
    },
    cerrarPerfil: () => setPerfilCerrado(true),
    detailData,
    detailLoading,
    /** El fallo del perfil del órgano: se dice en el perfil, no como «sin datos». */
    detailError,
    refetchDetail: () => void refetchDetail(),
    isLoading,
    error,
    /** El «Reintentar» del error. */
    refetch: () => void refetch(),
  };
}
