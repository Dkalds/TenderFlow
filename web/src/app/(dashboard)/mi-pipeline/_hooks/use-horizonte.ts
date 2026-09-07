"use client";

/**
 * Datos y acciones del horizonte de renovaciones.
 *
 * Los KPIs son totales del dataset completo servidos por el backend y la tabla
 * es el top-N que el SQL ya devuelve ordenado por oportunidad (ADR-014: aquí no
 * se agrega ni se reordena nada). Lo único que se calcula en el navegador es el
 * `_score` que pinta la columna «Oportunidad» —con la misma fórmula del backend,
 * fijada por `tests/test_renovaciones_score.py`— y la búsqueda local sobre las
 * filas ya servidas.
 */

import * as React from "react";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { useCreatePursuit } from "@/hooks/use-pursuits";
import { useOrganizationStore } from "@/hooks/use-organization";
import { fetchWithAuth } from "@/lib/api-client";
import type { Renovacion, RenovacionesResult, RenovacionesResumenResult } from "@/lib/api-types";
import { useFilters } from "@/lib/filters";
import { truncate } from "@/lib/utils";
import { opportunityScore } from "@/lib/opportunity-score";

// Las formas de renovaciones vienen del contrato OpenAPI
// (`services/competitive/renovaciones.py`), no se declaran aquí: estas
// interfaces existían a mano porque las rutas devolvían `dict[str, Any]`.
// Ver scripts/check_openapi_contract.py.

export const HORIZONTES = [
  { value: "3", label: "3 meses" },
  { value: "6", label: "6 meses" },
  { value: "12", label: "12 meses" },
  { value: "24", label: "24 meses" },
];

/**
 * Cuántas oportunidades pide la tabla. El backend ordena por score
 * (`order_by=score`), así que estas son las N mayores del dataset completo y
 * no las N primeras por fecha de fin: ese era el fallo que obligaba a pedir
 * 1000 filas y reordenarlas aquí.
 */
export const TOP_OPORTUNIDADES = 200;

/**
 * Días por mes con los que se convierte el horizonte en escala de urgencia.
 * Tiene que ser el mismo número que `DIAS_POR_MES` en
 * `db/repositories/renovaciones.py`: el servidor ordena con ese valor y aquí
 * se pinta el badge relativo con el mismo, así que si se separan la tabla
 * mostraría un orden y unos números que no se corresponden.
 */
const DIAS_POR_MES = 30;

/** Fila de la tabla: lo que sirve el endpoint más su score de oportunidad. */
export type RenovacionRow = Renovacion & { _score: number };

export function useHorizonte() {
  const router = useRouter();
  const [meses, setMeses] = useState("6");
  const [empresaSearch, setEmpresaSearch] = useState("");

  // Anticipar: abre un pursuit sobre el contrato que vence, antes de que la
  // relicitación se publique. Mismo flujo de creación que el Radar; la agenda
  // de Mi Pipeline deja de listar la renovación en cuanto existe el pursuit.
  const createPursuit = useCreatePursuit();
  const setActiveOrganizationId = useOrganizationStore((state) => state.setActiveOrganizationId);
  const anticipar = React.useCallback(
    async (licitacionId: string) => {
      try {
        const pursuit = await createPursuit.mutateAsync({ licitacion_id: licitacionId });
        setActiveOrganizationId(pursuit.organization_id);
        toast.success("Renovación anticipada como pursuit");
        router.push(`/oportunidades/${pursuit.id}`);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "No se pudo anticipar la renovación");
      }
    },
    [createPursuit, router, setActiveOrganizationId],
  );

  const abrirDetalle = React.useCallback(
    (licitacionId: string) => router.push(`/detalle?lic=${encodeURIComponent(licitacionId)}`),
    [router],
  );

  // Filtro global de la barra superior. Solo aplicamos "tecnología" aquí:
  // el endpoint de renovaciones filtra por licitaciones.tecnologia.
  const { tecnologias } = useFilters();
  const tecnologiaParam = tecnologias.join(",");
  const tecnologiaQs = tecnologiaParam ? `&tecnologia=${encodeURIComponent(tecnologiaParam)}` : "";

  const { data, isLoading, error } = useQuery<RenovacionesResult>({
    queryKey: ["renovaciones", meses, tecnologiaParam],
    queryFn: () =>
      fetchWithAuth(
        // Esta lista alimenta **solo la tabla virtualizada**; los KPIs de
        // arriba son totales del servidor sobre el dataset completo. El orden
        // por oportunidad lo hace el SQL (`order_by=score`), así que estas
        // filas son el top-N real de la ventana y no hace falta traerse un
        // sample grande para reordenarlo aquí.
        `/api/v1/competitive/renovaciones?months=${meses}&order_by=score` +
          `&limit=${TOP_OPORTUNIDADES}${tecnologiaQs}`,
      ),
    staleTime: 5 * 60 * 1000,
  });

  const { data: resumen } = useQuery<RenovacionesResumenResult>({
    queryKey: ["renovaciones-resumen", meses, tecnologiaParam],
    queryFn: () => fetchWithAuth(`/api/v1/competitive/renovaciones/resumen?months=${meses}${tecnologiaQs}`),
    staleTime: 5 * 60 * 1000,
  });

  const horizonteDias = Number(meses) * DIAS_POR_MES;

  // El score ya no ordena —eso lo hace el SQL— pero sí se pinta: la columna
  // "Oportunidad" muestra cada fila relativa al máximo del top servido, y para
  // eso hace falta el número. Misma fórmula que la del backend, fijada por
  // tests/test_renovaciones_score.py.
  const scored = useMemo(
    () =>
      (data?.items ?? []).map((r) => ({
        ...r,
        _score: opportunityScore({
          riesgoCambio: r.riesgo_cambio,
          importe: r.importe_adjudicado,
          diasRestantes: r.dias_restantes,
          horizonteDias,
        }),
      })),
    [data, horizonteDias],
  );

  // Búsqueda local sobre el top servido; conserva el orden del servidor.
  const items = useMemo(() => {
    if (!empresaSearch) return scored;
    const q = empresaSearch.toLowerCase();
    return scored.filter(
      (r) =>
        (r.empresa ?? "").toLowerCase().includes(q) ||
        (r.organo_contratacion ?? "").toLowerCase().includes(q) ||
        (r.titulo ?? "").toLowerCase().includes(q),
    );
  }, [scored, empresaSearch]);

  // Referencia del badge: el máximo del top completo, no el del subconjunto
  // filtrado — si no, escribir en la caja de búsqueda reescalaría la columna.
  const maxScore = useMemo(() => scored.reduce((m, r) => Math.max(m, r._score), 0), [scored]);

  const topCartera = useMemo(
    () =>
      (resumen?.items ?? []).slice(0, 10).map((r) => ({
        empresa: truncate(r.empresa ?? "—", 28),
        importe: r.importe_en_juego,
        contratos: r.contratos_venciendo,
      })),
    [resumen],
  );

  return {
    meses,
    setMeses,
    empresaSearch,
    setEmpresaSearch,
    isLoading,
    error,
    items,
    maxScore,
    // Los KPIs son totales del dataset completo servidos por el backend, no una
    // agregación sobre la página cargada (ADR-014 §2).
    totales: resumen?.totales,
    topCartera,
    anticipar,
    abrirDetalle,
  };
}

export type Horizonte = ReturnType<typeof useHorizonte>;
