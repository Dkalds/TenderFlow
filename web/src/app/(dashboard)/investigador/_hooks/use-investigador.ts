"use client";

/**
 * Estado y llamadas de la consola del Investigador.
 *
 * Un único hook para los dos modos porque comparten caja de texto, historial y
 * ajustes: `search` resuelve `POST /api/v1/search/semantic` y `ask` delega en
 * `useChat` (streaming e historial multi-turno). La configuración se persiste
 * en `localStorage` y se lee tras el montaje para no romper la hidratación.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchWithAuth } from "@/lib/api-client";
import { registrarEvento } from "@/lib/analytics";
import { useFilters } from "@/lib/filters";
import { useAskModels, useChat, type UseChatResult } from "@/hooks/use-ask";
import {
  DEFAULT_CONFIG,
  MAX_HISTORY,
  loadConfig,
  loadHistory,
  saveConfig,
  saveHistory,
} from "../_lib/config-storage";
import type { InvestigadorConfig, Mode, SearchResult } from "../_lib/types";

/** Respuesta de la búsqueda semántica: `hits` es la forma vigente del contrato. */
interface SemanticResponse {
  hits?: SearchResult[];
  results?: SearchResult[];
  items?: SearchResult[];
  source?: string;
}

export interface UseInvestigadorResult {
  mode: Mode;
  setMode: (mode: Mode) => void;
  query: string;
  setQuery: (query: string) => void;
  loading: boolean;
  error: string | null;
  searchResults: SearchResult[] | null;
  /** Fuente REAL de la última búsqueda, tal cual la devuelve el backend. */
  searchSource: string | null;
  history: string[];
  config: InvestigadorConfig;
  updateConfig: (patch: Partial<InvestigadorConfig>) => void;
  models: string[] | undefined;
  /** Chips de los filtros globales que acotan la búsqueda, si están activos. */
  activeSearchFilters: string[];
  chat: UseChatResult;
  /** `true` cuando no hay ni resultados ni conversación ni error que mostrar. */
  showEmpty: boolean;
  submit: (overrideQuery?: string) => void;
}

export function useInvestigador(): UseInvestigadorResult {
  const [mode, setMode] = useState<Mode>("search");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);
  const [searchSource, setSearchSource] = useState<string | null>(null);
  const [history, setHistory] = useState<string[]>([]);
  const [config, setConfig] = useState<InvestigadorConfig>(DEFAULT_CONFIG);
  const abortRef = useRef<AbortController | null>(null);

  // Modo "Preguntar": hilo de chat multi-turno (historial en cliente).
  const chat = useChat();
  const chatSend = chat.send;

  const globalFilters = useFilters();

  // Filtros activos sobre la búsqueda (chips), para que la relación sea explícita
  // y no un flag escondido: si está activado, se ve qué acota los resultados.
  const activeSearchFilters = useMemo(() => {
    if (!config.useGlobalFilters) return [] as string[];
    const chips = [...globalFilters.ccaas, ...globalFilters.tecnologias];
    if (globalFilters.rango.desde || globalFilters.rango.hasta) {
      chips.push(`${globalFilters.rango.desde ?? "…"} → ${globalFilters.rango.hasta ?? "…"}`);
    }
    return chips;
  }, [config.useGlobalFilters, globalFilters]);

  // Estado persistido: se carga tras el montaje para evitar el desajuste de
  // hidratación con el HTML del servidor.
  useEffect(() => {
    setHistory(loadHistory()); // eslint-disable-line react-hooks/set-state-in-effect
    setConfig(loadConfig());
  }, []);

  // Catálogo de modelos. Era una segunda `queryFn` bajo la misma clave
  // `["ask-models"]` que `hooks/use-ask.ts` —sin tipar, con `fetch` crudo y una
  // rama para un array pelado que la API nunca devuelve—, así que el contenido
  // del selector dependía de cuál de las dos montara primero. Queda la tipada.
  const { data: models } = useAskModels();

  const updateConfig = useCallback((patch: Partial<InvestigadorConfig>) => {
    setConfig((prev) => {
      const next = { ...prev, ...patch };
      saveConfig(next);
      return next;
    });
  }, []);

  const addHistory = useCallback((q: string) => {
    setHistory((prev) => {
      const filtered = prev.filter((h) => h !== q);
      const next = [q, ...filtered].slice(0, MAX_HISTORY);
      saveHistory(next);
      return next;
    });
  }, []);

  const runSearch = useCallback(
    async (q: string, filterExtras: Record<string, unknown>) => {
      abortRef.current?.abort();
      const abort = new AbortController();
      abortRef.current = abort;

      setLoading(true);
      setError(null);
      setSearchResults(null);
      setSearchSource(null);

      try {
        // `fetchWithAuth` adjunta el CSRF en las mutaciones (el ensamblado a
        // mano de la cabecera era una copia local de eso) y normaliza el error
        // a `ApiError` con el `detail` RFC-7807.
        const data = await fetchWithAuth<SemanticResponse>("/api/v1/search/semantic", {
          method: "POST",
          body: JSON.stringify({
            q,
            top_k: config.topK,
            alpha: config.alpha,
            ...filterExtras,
          }),
          signal: abort.signal,
        });
        const hits: SearchResult[] = data.hits ?? data.results ?? data.items ?? [];
        setSearchResults(hits);
        setSearchSource(data.source ?? null);
        // Boca del embudo. `con_resultados` es lo que separa uso de fricción:
        // una búsqueda que no devuelve nada no dice que el producto sirva.
        // El término buscado NO viaja — es la estrategia comercial de quien lo
        // escribe, igual que las keywords de una regla de vigilancia.
        registrarEvento("busqueda_realizada", {
          superficie: "investigador",
          con_resultados: hits.length > 0 ? "si" : "no",
        });
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err instanceof Error ? err.message : "Error desconocido");
      } finally {
        setLoading(false);
      }
    },
    [config.topK, config.alpha],
  );

  const submit = useCallback(
    (overrideQuery?: string) => {
      const q = (overrideQuery ?? query).trim();
      if (!q) return;
      addHistory(q);

      // Filtros globales → se mandan TODOS los valores (no solo el primero) y el
      // backend restringe los resultados (allowed_ids). Antes se enviaba
      // ccaas[0]/tecnologias[0] a un endpoint inexistente (/api/v1/search): falsa
      // sensacion de filtrado y, de hecho, busqueda rota (ADR-014).
      const filterExtras: Record<string, unknown> = {};
      if (config.useGlobalFilters) {
        if (globalFilters.ccaas.length > 0) filterExtras.ccaa = globalFilters.ccaas;
        if (globalFilters.tecnologias.length > 0) filterExtras.tecnologia = globalFilters.tecnologias;
        if (globalFilters.rango.desde) filterExtras.fecha_desde = globalFilters.rango.desde;
        if (globalFilters.rango.hasta) filterExtras.fecha_hasta = globalFilters.rango.hasta;
      }

      if (mode === "ask") {
        // Chat multi-turno — el hook gestiona historial, streaming y abort.
        setQuery("");
        void chatSend(q, {
          model: config.model || undefined,
          topK: config.topK,
          extras: filterExtras,
        });
        return;
      }

      void runSearch(q, filterExtras);
    },
    [query, mode, config, globalFilters, addHistory, chatSend, runSearch],
  );

  const showEmpty =
    !loading && !error && !searchResults && chat.messages.length === 0 && !chat.loading && !chat.error;

  return {
    mode,
    setMode,
    query,
    setQuery,
    loading,
    error,
    searchResults,
    searchSource,
    history,
    config,
    updateConfig,
    models,
    activeSearchFilters,
    chat,
    showEmpty,
    submit,
  };
}
