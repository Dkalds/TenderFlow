"use client";

/**
 * Estado y llamadas de la consola del Investigador.
 *
 * Una sola caja. Lo que se escribe siempre se busca
 * (`POST /api/v1/search/semantic`) y, si además es una pregunta, el asistente
 * la responde (`use-asistente.ts`). Hasta 2026-10 eran dos modos que había que
 * elegir antes de escribir, y se excluían.
 *
 * - **La consulta vive en la URL** (`?consulta=`) y sus resultados en la caché
 *   de React Query, con la petición entera en la clave. Abrir una ficha y
 *   volver encuentra la lista donde estaba; antes era estado local y se perdía.
 * - **El ámbito** de la barra viaja igual a la lista y al asistente.
 * - Los ajustes se leen de `localStorage` tras el montaje (`use-ajustes.ts`) y
 *   la búsqueda espera a tenerlos.
 */

import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { parseAsString, useQueryStates } from "nuqs";
import { fetchWithAuth } from "@/lib/api-client";
import type { FiltrosCorpus } from "@/lib/api-types";
import { registrarEvento } from "@/lib/analytics";
import { useFilters } from "@/lib/filters";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { investigadorKeys } from "@/lib/query-keys";
import { formatDate } from "@/lib/utils";
import { useAskModels, type UseChatResult } from "@/hooks/use-ask";
import { esPregunta } from "../_lib/pregunta";
import { FUENTE_CON_SIGNIFICADO } from "../_lib/source-label";
import type { Interpretacion, InvestigadorConfig, SearchResult, SemanticSearchResponse } from "../_lib/types";
import { useAjustes } from "./use-ajustes";
import { useAsistente, type ExpedienteMarcado } from "./use-asistente";

export { MAX_EXPEDIENTES_ASISTENTE, type ExpedienteMarcado } from "./use-asistente";

const PARAMETROS = {
  consulta: parseAsString.withDefault(""),
  tal_cual: parseAsString.withDefault(""),
};

export interface UseInvestigadorResult {
  /** Lo que hay escrito en la caja. */
  texto: string;
  setTexto: (texto: string) => void;
  /** La consulta que se buscó: la de la URL. Vacía si aún no se ha buscado. */
  consulta: string;
  /** Busca lo escrito (o `override`) y, si es una pregunta, la responde. */
  submit: (override?: string) => void;

  /** `true` mientras llega la primera respuesta de una consulta. */
  loading: boolean;
  /** Lo que lanzó la búsqueda, tal cual: `PanelError` saca de ahí el mensaje humano y el detalle técnico. */
  error: unknown;
  reintentar: () => void;
  searchResults: SearchResult[] | null;
  /** Fuente REAL de la última búsqueda, tal cual llega en la respuesta. */
  searchSource: string | null;
  /** Los filtros que salieron de la frase y se aplicaron. */
  interpretacion: Interpretacion | null;
  /** La búsqueda se hizo con el texto tal cual, sin leer filtros en la frase. */
  talCual: boolean;
  setTalCual: (talCual: boolean) => void;

  history: string[];
  config: InvestigadorConfig;
  updateConfig: (patch: Partial<InvestigadorConfig>) => void;
  models: string[] | undefined;
  /** Alguna respuesta combinó significado y texto: «Tipo de coincidencia» gobierna algo. */
  fusionDisponible: boolean;
  /** Chips del ámbito que acota la búsqueda, si está activo. */
  activeSearchFilters: string[];
  /** El ámbito tal como viaja: lo usa «Crear alerta» para llevárselo. */
  filtros: FiltrosCorpus;

  chat: UseChatResult;
  /** Pregunta al asistente sobre lo marcado. Con `nueva`, en una conversación nueva. */
  preguntar: (pregunta: string, opciones?: { nueva?: boolean }) => void;
  /** Los resultados marcados: sobre ellos responde el asistente. Vacío: sobre todas las licitaciones. */
  seleccion: ExpedienteMarcado[];
  alternarSeleccion: (resultado: SearchResult) => void;
  quitarSeleccion: (id: string) => void;
  /** Ya hay tres marcados: no cabe otro. */
  seleccionLlena: boolean;

  /** `true` cuando no hay ni consulta ni conversación que mostrar. */
  showEmpty: boolean;
}

export function useInvestigador(): UseInvestigadorResult {
  // `push`: cada consulta es una entrada del historial, así que «atrás» vuelve
  // a la búsqueda anterior y no a la pantalla de antes del Investigador.
  const [parametros, setParametros] = useQueryStates(PARAMETROS, { history: "push", shallow: true });
  const consulta = parametros.consulta.trim();
  const talCual = parametros.tal_cual === "1";

  const [texto, setTexto] = useState(consulta);
  // La caja sigue a la URL cuando esta cambia por fuera (atrás, adelante, un
  // enlace): se ajusta durante el render, sin un efecto que pinte dos veces.
  const [consultaVista, setConsultaVista] = useState(consulta);
  if (consultaVista !== consulta) {
    setConsultaVista(consulta);
    setTexto(consulta);
  }

  const { config, lista: ajustesListos, updateConfig, history, addHistory } = useAjustes();
  const [fusionDisponible, setFusionDisponible] = useState(false);
  const { data: models } = useAskModels();

  // Ámbito → se mandan TODOS los valores (no solo el primero) y la búsqueda los
  // aplica en su propia consulta. El mismo objeto va a la lista y al asistente:
  // `FiltrosCorpus` lo ata a los dos contratos.
  const { ccaas, tecnologias, rango } = useFilters();
  const ccaasClave = ccaas.join();
  const tecnologiasClave = tecnologias.join();
  const filtros = useMemo<FiltrosCorpus>(() => {
    const extras: FiltrosCorpus = {};
    if (!config.useGlobalFilters) return extras;
    if (ccaas.length > 0) extras.ccaa = ccaas;
    if (tecnologias.length > 0) extras.tecnologia = tecnologias;
    if (rango.desde) extras.fecha_desde = rango.desde;
    if (rango.hasta) extras.fecha_hasta = rango.hasta;
    return extras;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- las listas entran por su clave estable
  }, [config.useGlobalFilters, ccaasClave, tecnologiasClave, rango.desde, rango.hasta]);

  // Los mismos filtros, a la vista: si el ámbito acota, se ve qué acota.
  const activeSearchFilters = useMemo(() => {
    const chips = [...(filtros.ccaa ?? []), ...(filtros.tecnologia ?? [])];
    const { fecha_desde: desde, fecha_hasta: hasta } = filtros;
    // Fechas en la forma de la casa («1 jul 2026»), no en ISO: el chip se lee.
    if (desde || hasta) chips.push(`${desde ? formatDate(desde) : "…"} → ${hasta ? formatDate(hasta) : "…"}`);
    return chips;
  }, [filtros]);

  const peticion = useMemo(
    () => ({
      q: consulta,
      top_k: config.topK,
      alpha: config.alpha,
      interpretar: !talCual,
      ...filtros,
    }),
    [consulta, config.topK, config.alpha, talCual, filtros],
  );

  const busqueda = useQuery({
    queryKey: investigadorKeys.busqueda(peticion),
    queryFn: async ({ signal }) => {
      // `fetchWithAuth` adjunta el CSRF en las mutaciones y normaliza el error
      // a `ApiError` con el `detail` RFC-7807.
      const data = await fetchWithAuth<SemanticSearchResponse>("/api/v1/search/semantic", {
        method: "POST",
        body: JSON.stringify(peticion),
        signal,
      });
      // Boca del embudo. `con_resultados` es lo que separa uso de fricción:
      // una búsqueda que no devuelve nada no dice que el producto sirva. Va
      // aquí y no al pintar: la lista que vuelve de la caché no es otra
      // búsqueda. El término buscado NO viaja — es la estrategia comercial de
      // quien lo escribe, igual que las keywords de una regla de vigilancia.
      registrarEvento("busqueda_realizada", {
        superficie: "investigador",
        con_resultados: data.hits.length > 0 ? "si" : "no",
      });
      return data;
    },
    enabled: ajustesListos && consulta.length > 0,
    // Los anuncios no cambian de un minuto a otro: volver de una ficha
    // encuentra la lista sin esperar ni pedirla otra vez.
    staleTime: 5 * 60_000,
    gcTime: 15 * 60_000,
    retry: false,
    // El fallo se pinta en la propia pantalla, con su «Reintentar».
    meta: META_ERROR_EN_LINEA,
  });

  const searchSource = busqueda.data?.source ?? null;
  // «Tipo de coincidencia» solo aparece cuando una respuesta ha combinado de
  // verdad significado y texto. Se queda puesto el resto de la visita: quien
  // lo mueve tiene que poder seguir viéndolo aunque la siguiente no combine.
  if (!fusionDisponible && searchSource === FUENTE_CON_SIGNIFICADO) setFusionDisponible(true);

  const asistente = useAsistente({ config, filtros, talCual });
  const { preguntarSobreTodo, soltarSeleccion } = asistente;

  const { refetch } = busqueda;
  const submit = useCallback(
    (override?: string) => {
      const q = (override ?? texto).trim();
      if (!q) return;
      addHistory(q);
      setTexto(q);
      // Una consulta nueva es otra investigación: los resultados marcados eran
      // de la lista anterior.
      soltarSeleccion();
      if (q === consulta && !talCual) {
        void refetch();
      } else {
        // Se vuelve a leer la frase: «tal cual» era una decisión sobre la
        // consulta anterior.
        void setParametros({ consulta: q, tal_cual: null });
      }
      // La pregunta va sobre todas las licitaciones, en una conversación
      // nueva; las de seguimiento se hacen desde el propio hilo.
      if (esPregunta(q)) preguntarSobreTodo(q);
    },
    [texto, consulta, talCual, addHistory, refetch, setParametros, soltarSeleccion, preguntarSobreTodo],
  );

  const setTalCual = useCallback(
    (valor: boolean) => void setParametros({ tal_cual: valor ? "1" : null }),
    [setParametros],
  );

  return {
    texto,
    setTexto,
    consulta,
    submit,
    // También mientras se leen los ajustes guardados: con una consulta en la
    // URL, ese instante es «buscando», no «sin nada que enseñar».
    loading: consulta.length > 0 && (busqueda.isLoading || !ajustesListos),
    error: busqueda.error,
    reintentar: () => void refetch(),
    searchResults: busqueda.data?.hits ?? null,
    searchSource,
    interpretacion: busqueda.data?.interpretacion ?? null,
    talCual,
    setTalCual,
    history,
    config,
    updateConfig,
    models,
    fusionDisponible,
    activeSearchFilters,
    filtros,
    chat: asistente.chat,
    preguntar: asistente.preguntar,
    seleccion: asistente.seleccion,
    alternarSeleccion: asistente.alternarSeleccion,
    quitarSeleccion: asistente.quitarSeleccion,
    seleccionLlena: asistente.seleccionLlena,
    showEmpty: consulta.length === 0 && !asistente.hayConversacion,
  };
}
