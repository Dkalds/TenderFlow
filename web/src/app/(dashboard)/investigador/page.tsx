"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import {
  Search,
  MessageSquare,
  Settings,
  Download,
  Clock,
  Sparkles,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { formatCurrency, truncate } from "@/lib/utils";
import { getJSON, setJSON } from "@/lib/storage";
import { useFilters } from "@/lib/filters";
import { useChat } from "@/hooks/use-ask";
import { ChatThread } from "@/components/chat-thread";
import { SpaceShell } from "@/components/layout/space-shell";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type Mode = "search" | "ask";

interface SearchResult {
  id_externo?: string;
  titulo?: string;
  organo_contratacion?: string;
  organo?: string;
  importe?: number;
  score?: number;
  source?: string;
  description?: string;
  id?: string;
  expediente?: string;
}

interface InvestigadorConfig {
  topK: number;
  model: string;
  alpha: number;
  useGlobalFilters: boolean;
}

const CONFIG_KEY = "investigador_config";
const HISTORY_KEY = "search_history";

const DEFAULT_CONFIG: InvestigadorConfig = {
  topK: 10,
  model: "",
  alpha: 0.7,
  useGlobalFilters: false,
};

const EXAMPLE_QUESTIONS = [
  "Cuales son las licitaciones mas recientes?",
  "Que es un PCAP y que contiene?",
  "Como funciona el procedimiento abierto simplificado?",
  "Resumen de licitaciones de mantenimiento en Madrid",
  "Buscar licitaciones de S/4HANA con importe mayor a 500K",
];

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function loadConfig(): InvestigadorConfig {
  const raw = getJSON<Partial<InvestigadorConfig>>(CONFIG_KEY, {});
  return { ...DEFAULT_CONFIG, ...raw };
}

function saveConfig(cfg: InvestigadorConfig) {
  setJSON(CONFIG_KEY, cfg);
}

function loadHistory(): string[] {
  return getJSON<string[]>(HISTORY_KEY, []);
}

function saveHistory(h: string[]) {
  setJSON(HISTORY_KEY, h);
}

function relevanceBadge(score: number | undefined) {
  if (score == null) return null;
  if (score >= 0.8) return <Badge className="bg-green-600 text-white hover:bg-green-700">Alta</Badge>;
  if (score >= 0.5) return <Badge className="bg-yellow-500 text-white hover:bg-yellow-600">Media</Badge>;
  return <Badge variant="secondary">Baja</Badge>;
}

function highlightQuery(text: string, query: string) {
  if (!query.trim()) return text;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = text.split(new RegExp(`(${escaped})`, "gi"));
  return parts.map((part, i) =>
    part.toLowerCase() === query.toLowerCase() ? (
      <mark key={i} className="bg-yellow-200 font-semibold dark:bg-yellow-800">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

function exportCSV(results: SearchResult[]) {
  const headers = ["id_externo", "titulo", "organo", "importe", "score", "source"];
  const rows = results.map((r) =>
    [
      r.id_externo ?? r.id ?? "",
      `"${(r.titulo ?? "").replace(/"/g, '""')}"`,
      `"${(r.organo_contratacion ?? r.organo ?? "").replace(/"/g, '""')}"`,
      r.importe ?? "",
      r.score != null ? r.score.toFixed(4) : "",
      r.source ?? "",
    ].join(","),
  );
  const csv = [headers.join(","), ...rows].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `investigador_resultados_${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/* ------------------------------------------------------------------ */
/*  Page component                                                     */
/* ------------------------------------------------------------------ */

export default function InvestigadorPage() {
  const [mode, setMode] = useState<Mode>("search");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);
  const [history, setHistory] = useState<string[]>([]);
  const [config, setConfig] = useState<InvestigadorConfig>(DEFAULT_CONFIG);
  const [settingsOpen, setSettingsOpen] = useState(true);
  const abortRef = useRef<AbortController | null>(null);

  // Modo "Preguntar": hilo de chat multi-turno (historial en cliente).
  const chat = useChat();
  const chatSend = chat.send;

  // Global filters
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

  // Load persisted state after mount to avoid SSR hydration mismatch
  useEffect(() => {
    setHistory(loadHistory()); // eslint-disable-line react-hooks/set-state-in-effect
    setConfig(loadConfig());
  }, []);

  // Fetch available models
  const { data: models } = useQuery<string[]>({
    queryKey: ["ask-models"],
    queryFn: async () => {
      const res = await fetch("/api/v1/ask/models", {
        credentials: "include",
      });
      if (!res.ok) return [];
      const data = await res.json();
      return Array.isArray(data) ? data : (data.models ?? []);
    },
    staleTime: Infinity,
  });

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
      const next = [q, ...filtered].slice(0, 10);
      saveHistory(next);
      return next;
    });
  }, []);

  /* ---- Submit ---- */
  const handleSubmit = useCallback(
    async (overrideQuery?: string) => {
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
        await chatSend(q, {
          model: config.model || undefined,
          topK: config.topK,
          extras: filterExtras,
        });
        return;
      }

      // Modo búsqueda semántica (sin LLM).
      abortRef.current?.abort();
      const abort = new AbortController();
      abortRef.current = abort;

      setLoading(true);
      setError(null);
      setSearchResults(null);

      try {
        const res = await fetch("/api/v1/search/semantic", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            q,
            top_k: config.topK,
            alpha: config.alpha,
            ...filterExtras,
          }),
          signal: abort.signal,
        });
        if (!res.ok) throw new Error(`Error ${res.status}`);
        const data = await res.json();
        const hits: SearchResult[] = data.hits ?? data.results ?? data.items ?? [];
        setSearchResults(hits);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err instanceof Error ? err.message : "Error desconocido");
      } finally {
        setLoading(false);
      }
    },
    [query, mode, config, globalFilters, addHistory, chatSend],
  );

  /* ---- Example chip click ---- */
  const handleExampleClick = useCallback(
    (q: string) => {
      setQuery(q);
      handleSubmit(q);
    },
    [handleSubmit],
  );

  const showEmpty = !loading && !error && !searchResults && chat.messages.length === 0 && !chat.loading && !chat.error;

  return (
    <SpaceShell spaceKey="investigador">
      <div className="space-y-6">
      {/* ---- Configuration panel ---- */}
      <Card>
        <CardHeader
          className="cursor-pointer py-3 select-none"
          onClick={() => setSettingsOpen((o) => !o)}
          tabIndex={0}
          role="button"
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              setSettingsOpen((o) => !o);
            }
          }}
        >
          <CardTitle className="flex items-center gap-2 text-sm">
            <Settings className="h-4 w-4" />
            Configuracion
            {settingsOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </CardTitle>
        </CardHeader>
        {settingsOpen && (
          <CardContent className="pt-0">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {/* top_k */}
              <div className="space-y-1">
                <label className="text-xs font-medium">top_k: {config.topK}</label>
                <Slider
                  value={[config.topK]}
                  onValueChange={([v]) => updateConfig({ topK: v })}
                  min={1}
                  max={50}
                  className="w-full"
                />
              </div>
              {/* Alpha */}
              <div className="space-y-1">
                <label className="text-xs font-medium">Alpha (FAISS vs FTS5): {config.alpha.toFixed(2)}</label>
                <Slider
                  value={[Math.round(config.alpha * 100)]}
                  onValueChange={([v]) => updateConfig({ alpha: v / 100 })}
                  min={0}
                  max={100}
                  className="w-full"
                />
              </div>
              {/* Model */}
              <div className="space-y-1">
                <label htmlFor="inv-model" className="text-xs font-medium">
                  Modelo LLM
                </label>
                <Select
                  value={config.model || "__default__"}
                  onValueChange={(v) => updateConfig({ model: v === "__default__" ? "" : v })}
                >
                  <SelectTrigger id="inv-model">
                    <SelectValue placeholder="Por defecto" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__default__">Por defecto</SelectItem>
                    {models?.map((m) => (
                      <SelectItem key={m} value={m}>
                        {m}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {/* Use global filters */}
              <div className="flex items-center gap-2 self-end pb-1">
                <Checkbox
                  id="use-global-filters"
                  checked={config.useGlobalFilters}
                  onCheckedChange={(checked) => updateConfig({ useGlobalFilters: !!checked })}
                  className="h-5 w-5"
                />
                <label htmlFor="use-global-filters" className="cursor-pointer text-xs font-medium">
                  Respetar filtros globales
                </label>
              </div>
            </div>
          </CardContent>
        )}
      </Card>

      {/* ---- Search bar ---- */}
      <Card>
        <CardContent className="pt-6">
          {/* Mode toggle */}
          <div className="mb-4 flex gap-2">
            <Button variant={mode === "search" ? "default" : "outline"} size="sm" onClick={() => setMode("search")}>
              <Search className="mr-2 h-4 w-4" />
              Busqueda
            </Button>
            <Button variant={mode === "ask" ? "default" : "outline"} size="sm" onClick={() => setMode("ask")}>
              <MessageSquare className="mr-2 h-4 w-4" />
              Preguntar
            </Button>
          </div>

          <div className="flex gap-2">
            <Input
              placeholder={
                mode === "search"
                  ? "Buscar licitaciones por texto semantico..."
                  : "Haz una pregunta sobre licitaciones..."
              }
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
              className="flex-1"
            />
            <Button onClick={() => handleSubmit()} disabled={loading || chat.loading || !query.trim()}>
              {loading || chat.loading
                ? mode === "search"
                  ? "Buscando..."
                  : "Preguntando..."
                : mode === "search"
                  ? "Buscar"
                  : "Preguntar"}
            </Button>
          </div>

          {/* History chips */}
          {history.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              <Clock className="text-muted-foreground mt-0.5 h-4 w-4" />
              {history.map((h) => (
                <Badge
                  key={h}
                  variant="secondary"
                  className="hover:bg-accent cursor-pointer"
                  role="button"
                  tabIndex={0}
                  onClick={() => {
                    setQuery(h);
                    handleSubmit(h);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setQuery(h);
                      handleSubmit(h);
                    }
                  }}
                >
                  {h}
                </Badge>
              ))}
            </div>
          )}

          {/* Filtros activos sobre la búsqueda: relación explícita (no un flag oculto) */}
          {activeSearchFilters.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="text-muted-foreground text-xs">Filtros activos:</span>
              {activeSearchFilters.map((f) => (
                <Badge key={f} variant="outline" className="text-xs">
                  {f}
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ---- Example question chips ---- */}
      {showEmpty && (
        <div>
          <div className="mb-3 flex items-center gap-2">
            <Sparkles className="text-muted-foreground h-4 w-4" />
            <span className="text-muted-foreground text-sm font-medium">Preguntas de ejemplo</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {EXAMPLE_QUESTIONS.map((eq) => (
              <Badge
                key={eq}
                variant="outline"
                className="hover:bg-accent cursor-pointer px-3 py-1.5 text-sm"
                role="button"
                tabIndex={0}
                onClick={() => handleExampleClick(eq)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    handleExampleClick(eq);
                  }
                }}
              >
                {eq}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* ---- Loading (búsqueda) ---- */}
      {loading && (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <Card key={i}>
              <CardContent className="space-y-2 pt-6">
                <Skeleton className="h-5 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-4 w-1/3" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* ---- Error ---- */}
      {error && (
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-destructive font-medium">Error: {error}</p>
          </CardContent>
        </Card>
      )}

      {/* Resultados y conversación **conviven**: antes se excluían, así que
          preguntar por un resultado te hacía perder la lista desde la que
          preguntabas. En pantalla ancha van en paneles contiguos. */}
      <div className="grid items-start gap-4 xl:grid-cols-2">
      {/* ---- Search results ---- */}
      {!loading && searchResults && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">{searchResults.length} resultados encontrados</h2>
            {searchResults.length > 0 && (
              <Button variant="outline" size="sm" onClick={() => exportCSV(searchResults)}>
                <Download className="mr-2 h-4 w-4" />
                Exportar CSV
              </Button>
            )}
          </div>
          {searchResults.length === 0 ? (
            <Card className="border-dashed">
              <CardContent className="text-muted-foreground py-8 text-center">
                No se encontraron resultados para tu busqueda.
              </CardContent>
            </Card>
          ) : (
            searchResults.map((r, i) => {
              const organo = r.organo_contratacion ?? r.organo ?? "";
              const rid = r.id_externo ?? r.id ?? String(i);
              const excerpt = r.description ? truncate(r.description, 200) : null;

              return (
                <Card key={rid}>
                  <CardHeader className="pb-2">
                    <div className="flex items-start justify-between gap-4">
                      <CardTitle className="text-base leading-snug">
                        <a
                          href={`/detalle?lic=${r.id_externo ?? r.id ?? r.expediente ?? ""}`}
                          className="hover:underline"
                        >
                          {r.titulo ?? "Sin titulo"}
                        </a>
                      </CardTitle>
                      <div className="flex shrink-0 items-center gap-2">
                        {relevanceBadge(r.score)}
                        {r.score != null && <Badge variant="outline">{(r.score * 100).toFixed(1)}%</Badge>}
                      </div>
                    </div>
                    {organo && <CardDescription>{organo}</CardDescription>}
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {/* Context excerpt */}
                    {excerpt && <p className="text-muted-foreground text-sm">{highlightQuery(excerpt, query)}</p>}
                    <div className="flex items-center gap-4">
                      {r.importe != null && <Badge variant="secondary">{formatCurrency(r.importe)}</Badge>}
                      {r.source && (
                        <Badge variant="outline" className="text-xs">
                          {r.source}
                        </Badge>
                      )}
                    </div>
                  </CardContent>
                </Card>
              );
            })
          )}
        </div>
      )}

      {/* ---- Hilo de chat (modo Preguntar) ---- */}
      {(chat.messages.length > 0 || chat.loading || chat.error) && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="flex items-center gap-2 text-base">
              <MessageSquare className="h-4 w-4" />
              Conversación
            </CardTitle>
            {chat.messages.length > 0 && !chat.loading && (
              <Button variant="ghost" size="sm" onClick={chat.reset}>
                Nueva conversación
              </Button>
            )}
          </CardHeader>
          <CardContent>
            <ChatThread messages={chat.messages} streaming={chat.streaming} loading={chat.loading} error={chat.error} />
          </CardContent>
        </Card>
      )}
      </div>

      {/* ---- Empty state (no example chips shown above already) ---- */}
      {showEmpty && (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <Search className="text-muted-foreground/50 mb-4 h-12 w-12" />
            <p className="text-muted-foreground text-lg font-medium">
              Introduce una consulta para buscar en el corpus de licitaciones
            </p>
            <p className="text-muted-foreground/70 mt-1 text-sm">
              Usa el modo &quot;Busqueda&quot; para resultados semanticos o &quot;Preguntar&quot; para conversar con el
              asistente (corpus + conocimiento general).
            </p>
          </CardContent>
        </Card>
      )}
      </div>
    </SpaceShell>
  );
}
