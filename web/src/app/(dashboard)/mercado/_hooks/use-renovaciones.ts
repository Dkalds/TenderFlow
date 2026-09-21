"use client";

/**
 * Datos, corte y acciones de la vista Renovaciones de Mercado.
 *
 * La pregunta es de mercado: qué contratos **de cualquier adjudicatario**
 * vencen en la ventana y quién los defiende. Por eso el dataset no se recorta a
 * la organización activa. Tus contratos viven en `Oportunidades → Cartera` y
 * sus plazos aparecen en la Agenda; aquí sólo se **marcan** para que no haya
 * que abrir otra pantalla para saber cuáles ya son tuyos.
 *
 * Los KPIs son totales del dataset completo servidos por el backend y la tabla
 * es el top-N que el SQL ya devuelve ordenado por oportunidad (ADR-014: aquí no
 * se agrega ni se reordena nada). Lo único que se calcula en el navegador es el
 * `_score` que pinta la columna «Oportunidad» —con la misma fórmula del backend,
 * fijada por `tests/test_renovaciones_score.py`—, la búsqueda local sobre las
 * filas ya servidas y el cruce fila a fila de `_propio` (ver abajo).
 *
 * El nombre `HORIZONTES` de las ventanas se conserva de cuando la vista se
 * llamaba «Horizonte» en Mi Pipeline (hasta 2026-09-20): siguen siendo eso,
 * horizontes temporales.
 */

import * as React from "react";
import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { useCreatePursuit, usePursuits } from "@/hooks/use-pursuits";
import { useCartera } from "@/hooks/use-cartera";
import { useDebounce } from "@/hooks/use-debounce";
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

/** Ventana por defecto: la que se sirve cuando la URL no dice otra cosa. */
export const MESES_POR_DEFECTO = "6";

/**
 * El corte vive en la URL, como el resto del espacio.
 *
 * `?meses=` es la ventana y `?renovacion_q=` el filtro local sobre las filas
 * servidas. El filtro **no** se llama `q` a propósito: `q` es la búsqueda del
 * ámbito global (`lib/filters.ts`) y en un espacio el ámbito sobrevive al
 * cambio de vista, así que escribir aquí «Indra» filtraría además Tiempo,
 * Geografía y las otras seis por ese texto. Mismo prefijo que el `?organo_q=`
 * de la vista Órganos, por lo mismo.
 */
export const PARAM_MESES = "meses";
export const PARAM_BUSQUEDA = "renovacion_q";

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

/** Qué relación tiene ya tu organización con el contrato que vence. */
export type MarcaPropia = "cartera" | "anticipada";

/** Fila de la tabla: lo que sirve el endpoint más lo que se deriva por fila. */
export type RenovacionRow = Renovacion & { _score: number; _propio: MarcaPropia | null };

/** La ventana pedida por la URL, o la de por defecto si no es una de las cuatro. */
function horizonteDeLaUrl(valor: string | null | undefined): string {
  return HORIZONTES.some((h) => h.value === valor) ? (valor as string) : MESES_POR_DEFECTO;
}

export function useRenovaciones() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // El estado manda y la URL lo refleja (no al revés): sembrar una vez y
  // escribir después evita el parpadeo del input controlado por la URL, que en
  // una caja de búsqueda se nota a cada tecla.
  const [meses, setMeses] = useState(() => horizonteDeLaUrl(searchParams?.get(PARAM_MESES)));
  const [empresaSearch, setEmpresaSearch] = useState(() => searchParams?.get(PARAM_BUSQUEDA) ?? "");
  const busquedaEnlazable = useDebounce(empresaSearch, 300);

  useEffect(() => {
    const actuales = new URLSearchParams(searchParams?.toString() ?? "");
    // Los valores por defecto no se escriben: abrir la vista no tiene por qué
    // reescribir la URL, y un `?meses=6&renovacion_q=` vacío no dice nada que
    // la URL limpia no diga ya.
    const mismos =
      (actuales.get(PARAM_MESES) ?? MESES_POR_DEFECTO) === meses &&
      (actuales.get(PARAM_BUSQUEDA) ?? "") === busquedaEnlazable;
    if (mismos) return;

    if (meses === MESES_POR_DEFECTO) actuales.delete(PARAM_MESES);
    else actuales.set(PARAM_MESES, meses);
    if (busquedaEnlazable) actuales.set(PARAM_BUSQUEDA, busquedaEnlazable);
    else actuales.delete(PARAM_BUSQUEDA);

    // `replace` y no `push`, como el conmutador de vistas: ajustar el corte no
    // es navegar, y un entry de historial por tecla dejaría el botón «atrás»
    // inservible.
    router.replace(`?${actuales.toString()}`, { scroll: false });
  }, [router, searchParams, meses, busquedaEnlazable]);

  // Anticipar: abre un pursuit sobre el contrato que vence, antes de que la
  // relicitación se publique. Mismo flujo de creación que el Radar; la Agenda
  // (`/mi-pipeline`) deja de listar la renovación en cuanto existe el pursuit.
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

  const {
    data,
    isLoading,
    error,
    refetch: recargarLista,
  } = useQuery<RenovacionesResult>({
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

  const { data: resumen, refetch: recargarResumen } = useQuery<RenovacionesResumenResult>({
    queryKey: ["renovaciones-resumen", meses, tecnologiaParam],
    queryFn: () => fetchWithAuth(`/api/v1/competitive/renovaciones/resumen?months=${meses}${tecnologiaQs}`),
    staleTime: 5 * 60 * 1000,
  });

  const recargar = React.useCallback(() => {
    void recargarLista();
    void recargarResumen();
  }, [recargarLista, recargarResumen]);

  /**
   * Qué contratos de la ventana ya son tuyos.
   *
   * Es un cruce **fila a fila** por `licitacion_id` entre dos listas que la API
   * ya sirve —la cartera de la organización y sus oportunidades— y sólo decide
   * qué se pinta en la última celda de cada fila. **De aquí no sale ningún
   * total ni KPI**: los cuatro de arriba son los del resumen del servidor sobre
   * el dataset completo, y contar estas marcas daría un número sobre las 200
   * filas servidas con pinta de total (ADR-014 §1).
   *
   * Sin organización resuelta las dos consultas están deshabilitadas y el mapa
   * queda vacío: la tabla se pinta entera ofreciendo «Anticipar», que es el
   * comportamiento de siempre. Lo mismo si la organización tiene más
   * oportunidades que la primera página del listado (50): puede faltar una
   * marca, nunca sobrar una — el falso negativo deja el CTA que ya había.
   */
  const cartera = useCartera();
  const pursuits = usePursuits();
  const marcasPropias = useMemo(() => {
    const marcas = new Map<string, MarcaPropia>();
    for (const pursuit of pursuits.data?.items ?? []) marcas.set(pursuit.licitacion_id, "anticipada");
    // La cartera pisa a la oportunidad a propósito: si el contrato es tuyo, su
    // renovación se prepara desde `Oportunidades → Cartera` (con la ventana de
    // relicitación delante), no con el «Anticipar» de esta tabla.
    for (const contrato of cartera.data ?? []) marcas.set(contrato.licitacion_id, "cartera");
    return marcas;
  }, [cartera.data, pursuits.data]);

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
        _propio: marcasPropias.get(r.licitacion_id) ?? null,
      })),
    [data, horizonteDias, marcasPropias],
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
    recargar,
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

export type Renovaciones = ReturnType<typeof useRenovaciones>;
