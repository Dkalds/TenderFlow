"use client";

/**
 * Estado y llamadas de la consola del Investigador.
 *
 * Una sola caja. Lo que se escribe siempre se busca
 * (`POST /api/v1/search/semantic`) y, si además es una pregunta, la responde
 * el asistente único de la consola, que se abre a un lado sin tapar la lista
 * (`use-asistente.ts`). Hasta 2026-10 eran dos modos que había que elegir
 * antes de escribir, y se excluían; y hasta entonces también el asistente era
 * propio del Investigador.
 *
 * - **La consulta vive en la URL** (`?consulta=`) y sus resultados en la caché
 *   de React Query, con la petición entera en la clave. Abrir una ficha y
 *   volver encuentra la lista donde estaba; antes era estado local y se perdía.
 * - **El ámbito** de la barra viaja igual a la lista y al asistente.
 * - Los ajustes se leen de `localStorage` tras el montaje (`use-ajustes.ts`) y
 *   la búsqueda espera a tenerlos.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { parseAsString, useQueryStates } from "nuqs";
import { fetchWithAuth } from "@/lib/api-client";
import type { FiltrosCorpus } from "@/lib/api-types";
import { registrarEvento } from "@/lib/analytics";
import { useFilters } from "@/lib/filters";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { investigadorKeys } from "@/lib/query-keys";
import { formatDate } from "@/lib/utils";
import { useAskModels } from "@/hooks/use-ask";
import { MAX_RESULTADOS, mismaBusquedaSalvoTopK } from "../_lib/paginas";
import { esPregunta } from "../_lib/pregunta";
import { FUENTE_CON_SIGNIFICADO } from "../_lib/source-label";
import type { Interpretacion, InvestigadorConfig, SearchResult, SemanticSearchResponse } from "../_lib/types";
import { useAjustes } from "./use-ajustes";
import { useAsistenteInvestigador, type ExpedienteMarcado } from "./use-asistente";

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
  /**
   * `true` mientras se pide algo, también si ya hay una lista en pantalla: al
   * repetir la consulta o al pedir más. Es lo que dice el botón «Buscar».
   */
  buscando: boolean;
  /** Lo que lanzó la búsqueda, tal cual: `PanelError` saca de ahí el mensaje humano y el detalle técnico. */
  error: unknown;
  reintentar: () => void;
  searchResults: SearchResult[] | null;
  /** Fuente REAL de la última búsqueda, tal cual llega en la respuesta. */
  searchSource: string | null;
  /** Los filtros que salieron de la frase y se aplicaron. */
  interpretacion: Interpretacion | null;
  /** La búsqueda tenía más resultados de los que se enseñan. */
  hayMas: boolean;
  /** Pide la siguiente tanda; `null` si no hay más o ya se llegó al tope. */
  mostrarMas: (() => void) | null;
  /** La siguiente tanda está en camino; la lista de antes sigue a la vista. */
  cargandoMas: boolean;
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

  /** Pregunta al asistente sobre lo marcado. Con `nueva`, en una conversación nueva. */
  preguntar: (pregunta: string, opciones?: { nueva?: boolean }) => void;
  /** Abre el asistente sobre lo marcado (o sobre todo), sin preguntar todavía. */
  abrirAsistente: () => void;
  /** Los resultados marcados: sobre ellos responde el asistente. Vacío: sobre todas las licitaciones. */
  seleccion: ExpedienteMarcado[];
  alternarSeleccion: (resultado: SearchResult) => void;
  quitarSeleccion: (id: string) => void;
  /** Ya hay tres marcados: no cabe otro. */
  seleccionLlena: boolean;

  /**
   * `true` cuando no hay consulta que mostrar. La conversación no cuenta: vive
   * en el asistente, a un lado, y no ocupa la pantalla.
   */
  showEmpty: boolean;
}

export function useInvestigador(): UseInvestigadorResult {
  // `push`: cada consulta es una entrada del historial, así que «atrás» vuelve
  // a la búsqueda anterior y no a la pantalla de antes del Investigador.
  const [parametros, setParametros] = useQueryStates(PARAMETROS, { history: "push", shallow: true });
  const consulta = parametros.consulta.trim();
  const talCual = parametros.tal_cual === "1";

  const [texto, setTexto] = useState(consulta);
  // Resultados pedidos de más con «Mostrar más», sobre los de «Resultados».
  const [extra, setExtra] = useState(0);
  // La caja sigue a la URL cuando esta cambia por fuera (atrás, adelante, un
  // enlace): se ajusta durante el render, sin un efecto que pinte dos veces.
  // Una consulta nueva vuelve a la primera tanda.
  const [consultaVista, setConsultaVista] = useState(consulta);
  if (consultaVista !== consulta) {
    setConsultaVista(consulta);
    setTexto(consulta);
    setExtra(0);
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
      top_k: Math.min(config.topK + extra, MAX_RESULTADOS),
      alpha: config.alpha,
      interpretar: !talCual,
      ...filtros,
    }),
    [consulta, config.topK, extra, config.alpha, talCual, filtros],
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
      // «Mostrar más» no es otra búsqueda: no cuenta otra vez en el embudo.
      if (peticion.top_k <= config.topK) {
        registrarEvento("busqueda_realizada", {
          superficie: "investigador",
          con_resultados: data.hits.length > 0 ? "si" : "no",
        });
      }
      return data;
    },
    // «Mostrar más» enseña la lista que había mientras llega la siguiente
    // tanda; cualquier otro cambio de la petición es otra búsqueda.
    placeholderData: (previo, consultaPrevia) =>
      mismaBusquedaSalvoTopK(consultaPrevia?.queryKey, peticion) ? previo : undefined,
    enabled: ajustesListos && consulta.length > 0,
    // Los anuncios no cambian de un minuto a otro: volver de una ficha
    // encuentra la lista sin esperar ni pedirla otra vez.
    staleTime: 5 * 60_000,
    gcTime: 15 * 60_000,
    retry: false,
    // El fallo se pinta en la propia pantalla, con su «Reintentar».
    meta: META_ERROR_EN_LINEA,
  });

  // A «Recientes» va lo que se pudo buscar (también desde la caché, para que
  // volver a una consulta la suba): una que falla no se queda ahí.
  const buscada = busqueda.isSuccess && !busqueda.isPlaceholderData;
  useEffect(() => {
    if (buscada && consulta) addHistory(consulta);
  }, [buscada, consulta, addHistory]);

  const searchSource = busqueda.data?.source ?? null;
  // «Tipo de coincidencia» solo aparece cuando una respuesta ha combinado de
  // verdad significado y texto. Se queda puesto el resto de la visita: quien
  // lo mueve tiene que poder seguir viéndolo aunque la siguiente no combine.
  if (!fusionDisponible && searchSource === FUENTE_CON_SIGNIFICADO) setFusionDisponible(true);

  const asistente = useAsistenteInvestigador({ config, filtros, talCual });
  const { preguntarSobreTodo, soltarSeleccion } = asistente;

  // Una consulta nueva es otra investigación: los resultados marcados eran de
  // la lista anterior. Se suelta cuando cambia la consulta de la URL —también
  // con atrás y adelante— y no al pulsar «Buscar»: repetir la misma no cambia
  // la lista, y no tiene por qué borrar lo marcado. Solo si hay algo marcado:
  // una pregunta recién enviada sobre todas las licitaciones es del
  // Investigador y no se le quita el contexto.
  const consultaPrevia = useRef(consulta);
  const haySeleccion = asistente.seleccion.length > 0;
  useEffect(() => {
    if (consultaPrevia.current === consulta) return;
    consultaPrevia.current = consulta;
    if (haySeleccion) soltarSeleccion();
  }, [consulta, haySeleccion, soltarSeleccion]);

  const { refetch } = busqueda;
  const submit = useCallback(
    (override?: string) => {
      const q = (override ?? texto).trim();
      if (!q) return;
      setTexto(q);
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
    [texto, consulta, talCual, refetch, setParametros, preguntarSobreTodo],
  );

  const hayMas = Boolean(busqueda.data?.hay_mas);
  const mostrarMas = useCallback(() => setExtra((previo) => previo + config.topK), [config.topK]);

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
    buscando: consulta.length > 0 && (busqueda.isFetching || !ajustesListos),
    error: busqueda.error,
    reintentar: () => void refetch(),
    searchResults: busqueda.data?.hits ?? null,
    searchSource,
    interpretacion: busqueda.data?.interpretacion ?? null,
    hayMas,
    mostrarMas: hayMas && peticion.top_k < MAX_RESULTADOS ? mostrarMas : null,
    cargandoMas: busqueda.isPlaceholderData && busqueda.isFetching,
    talCual,
    setTalCual,
    history,
    config,
    updateConfig,
    models,
    fusionDisponible,
    activeSearchFilters,
    filtros,
    preguntar: asistente.preguntar,
    abrirAsistente: asistente.abrir,
    seleccion: asistente.seleccion,
    alternarSeleccion: asistente.alternarSeleccion,
    quitarSeleccion: asistente.quitarSeleccion,
    seleccionLlena: asistente.seleccionLlena,
    showEmpty: consulta.length === 0,
  };
}
