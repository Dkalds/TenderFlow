"use client";

import { useQueries } from "@tanstack/react-query";
import { Aviso } from "@/components/console/panel";
import { Comparator } from "@/components/comparator";
import { useMetaFilters } from "@/hooks/use-meta-filters";
import { fetchWithAuth } from "@/lib/api-client";
import type { LicitacionDetail as FichaApi } from "@/lib/api-types";
import type { LicitacionDetail } from "@/lib/licitacion-detail";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { licitacionKeys } from "@/lib/query-keys";
import type { MergedRow } from "../_hooks/detalle-table-model";

/**
 * El comparador de las filas seleccionadas, con la **ficha** de cada una.
 *
 * El listado no trae fuente, tipo de contrato, provincia, fechas de ejecución
 * ni descripción, y el comparador los enseñaba vacíos: comparaba seis campos
 * reales y seis rayas. Ahora pide `GET /licitaciones/{id}` por expediente con
 * la misma clave que el inspector —lo ya abierto no se vuelve a pedir— y,
 * mientras llega o si falla, la columna se queda con lo del listado y la línea
 * de arriba lo dice. La puntuación sigue saliendo de la fila: la ficha no la
 * trae.
 */
export function DetalleComparador({ filas, onClose }: { filas: MergedRow[]; onClose: () => void }) {
  const catalogo = useMetaFilters().data;
  const fichas = useQueries({
    queries: filas.map((row) => ({
      queryKey: licitacionKeys.detail(row.id_externo),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        fetchWithAuth<FichaApi>(`/api/v1/licitaciones/${encodeURIComponent(row.id_externo)}`, { signal }),
      staleTime: 5 * 60 * 1000,
      meta: META_ERROR_EN_LINEA,
    })),
  });

  const items: LicitacionDetail[] = filas.map((row, indice) => {
    const ficha = fichas[indice]?.data;
    return ficha ? { ...desdeFicha(ficha), score: row.score } : desdeListado(row);
  });
  const pendientes = fichas.filter((consulta) => consulta.isPending).length;
  const fallidas = filas.filter((_row, indice) => fichas[indice]?.isError).map((row) => row.id_externo);

  return (
    <Comparator
      items={items}
      catalogo={catalogo}
      onClose={onClose}
      aviso={
        pendientes > 0 || fallidas.length > 0 ? (
          <Aviso tone={fallidas.length > 0 ? "warning" : "info"} className="mb-3">
            {fallidas.length > 0
              ? `No se pudo cargar la ficha de ${fallidas.join(", ")}: sus campos de ficha salen vacíos.`
              : `Cargando la ficha de ${pendientes} ${pendientes === 1 ? "expediente" : "expedientes"}…`}
          </Aviso>
        ) : undefined
      }
    />
  );
}

/** La ficha de la API en la forma del comparador; lo que no publica, `null`. */
function desdeFicha(f: FichaApi): LicitacionDetail {
  return {
    id_externo: f.id_externo,
    titulo: f.titulo,
    organo_contratacion: f.organo_contratacion ?? null,
    importe: f.importe ?? null,
    estado: f.estado ?? null,
    fecha_publicacion: f.fecha_publicacion ?? null,
    ccaa: f.ccaa ?? null,
    cpv: f.cpv ?? null,
    url: f.url ?? null,
    fuente: f.fuente ?? null,
    tecnologia: f.tecnologia ?? null,
    tipo_contrato: f.tipo_contrato ?? null,
    provincia: f.provincia ?? null,
    fecha_limite: f.fecha_limite ?? null,
    fecha_inicio: f.fecha_inicio ?? null,
    fecha_fin: f.fecha_fin ?? null,
    descripcion: f.descripcion ?? null,
  };
}

/** Mientras llega la ficha, o si falla: lo que el listado sí trae, y `null` lo demás. */
function desdeListado(row: MergedRow): LicitacionDetail {
  return {
    id_externo: row.id_externo,
    titulo: row.titulo,
    organo_contratacion: row.organo_contratacion ?? null,
    importe: row.importe ?? null,
    estado: row.estado ?? null,
    fecha_publicacion: row.fecha_publicacion ?? null,
    ccaa: row.ccaa ?? null,
    cpv: row.cpv ?? null,
    url: row.url ?? null,
    fuente: null,
    tecnologia: row.tecnologia ?? null,
    tipo_contrato: null,
    provincia: null,
    // El listado sí trae la fecha límite: no hace falta esperar a la ficha.
    fecha_limite: row.fecha_limite ?? null,
    fecha_inicio: null,
    fecha_fin: null,
    descripcion: null,
    score: row.score,
  };
}
