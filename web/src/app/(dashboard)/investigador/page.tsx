"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import {
  Search,
  MessageSquare,
  BookOpen,
  Settings,
  Download,
  Clock,
  Sparkles,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { cn, formatCurrency, truncate } from "@/lib/utils";
import { getJSON, setJSON } from "@/lib/storage";
import { useFilters } from "@/lib/filters";

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
  "Que organos licitan mas en consultoria?",
  "Resumen de licitaciones de mantenimiento en Madrid",
  "Cual es la tendencia de importes en el ultimo ano?",
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
  if (score >= 0.8)
    return (
      <Badge className="bg-green-600 hover:bg-green-700 text-white">
        Alta
      </Badge>
    );
  if (score >= 0.5)
    return (
      <Badge className="bg-yellow-500 hover:bg-yellow-600 text-white">
        Media
      </Badge>
    );
  return <Badge variant="secondary">Baja</Badge>;
}

function highlightQuery(text: string, query: string) {
  if (!query.trim()) return text;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = text.split(new RegExp(`(${escaped})`, "gi"));
  return parts.map((part, i) =>
    part.toLowerCase() === query.toLowerCase() ? (
      <mark key={i} className="bg-yellow-200 dark:bg-yellow-800 font-semibold">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

function exportCSV(results: SearchResult[]) {
  const headers = [
    "id_externo",
    "titulo",
    "organo",
    "importe",
    "score",
    "source",
  ];
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
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(
    null,
  );
  const [askAnswer, setAskAnswer] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [history, setHistory] = useState<string[]>([]);
  const [config, setConfig] = useState<InvestigadorConfig>(DEFAULT_CONFIG);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Global filters
  const globalFilters = useFilters();

  // Load persisted state
  useEffect(() => {
    setHistory(loadHistory());
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
      return Array.isArray(data) ? data : data.models ?? [];
    },
    staleTime: Infinity,
  });

  const updateConfig = useCallback(
    (patch: Partial<InvestigadorConfig>) => {
      setConfig((prev) => {
        const next = { ...prev, ...patch };
        saveConfig(next);
        return next;
      });
    },
    [],
  );

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

      // Abort any previous streaming request
      abortRef.current?.abort();
      const abort = new AbortController();
      abortRef.current = abort;

      setLoading(true);
      setError(null);
      setSearchResults(null);
      setAskAnswer(null);
      setStreaming(false);
      addHistory(q);

      // Build filter params if enabled
      const filterExtras: Record<string, unknown> = {};
      if (config.useGlobalFilters) {
        if (globalFilters.ccaas.length > 0)
          filterExtras.ccaa = globalFilters.ccaas[0];
        if (globalFilters.tecnologias.length > 0)
          filterExtras.tecnologia = globalFilters.tecnologias[0];
      }

      try {
        if (mode === "search") {
          const res = await fetch("/api/v1/search", {
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
          const hits: SearchResult[] =
            data.hits ?? data.results ?? data.items ?? [];
          setSearchResults(hits);
        } else {
          // SSE streaming for Ask mode
          const res = await fetch("/api/v1/ask", {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              question: q,
              model: config.model || undefined,
              top_k: config.topK,
              ...filterExtras,
            }),
            signal: abort.signal,
          });
          if (!res.ok) throw new Error(`Error ${res.status}`);

          // Check if response is SSE or regular JSON
          const contentType = res.headers.get("content-type") ?? "";
          if (contentType.includes("text/event-stream") && res.body) {
            setStreaming(true);
            setAskAnswer("");
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let accumulated = "";
            let buffer = "";

            while (true) {
              const { done, value } = await reader.read();
              if (done) break;

              buffer += decoder.decode(value, { stream: true });
              const lines = buffer.split("\n");
              // Keep incomplete last line in buffer
              buffer = lines.pop() ?? "";

              for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed || !trimmed.startsWith("data: ")) continue;
                const payload = trimmed.slice(6);
                if (payload === "[DONE]") break;
                try {
                  const parsed = JSON.parse(payload);
                  if (parsed.text) {
                    accumulated += parsed.text;
                    setAskAnswer(accumulated);
                  }
                } catch {
                  // Non-JSON SSE line, accumulate as raw text
                  accumulated += payload;
                  setAskAnswer(accumulated);
                }
              }
            }
            setStreaming(false);
          } else {
            // Fallback: regular JSON response
            const data = await res.json();
            setAskAnswer(
              data.answer ?? data.text ?? "Sin respuesta disponible.",
            );
          }
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err instanceof Error ? err.message : "Error desconocido");
      } finally {
        setLoading(false);
        setStreaming(false);
      }
    },
    [query, mode, config, globalFilters, addHistory],
  );

  /* ---- Example chip click ---- */
  const handleExampleClick = useCallback(
    (q: string) => {
      setQuery(q);
      handleSubmit(q);
    },
    [handleSubmit],
  );

  /* ---- Render answer with clickable citations ---- */
  function renderAnswer(text: string) {
    // Match patterns like [id_externo] or references to IDs
    const parts = text.split(/(\b[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+(?:-[A-Z0-9]+)*\b)/g);
    return parts.map((part, i) => {
      // Heuristic: if it looks like an id_externo (has dashes, uppercase)
      if (/^[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+/.test(part)) {
        return (
          <a
            key={i}
            href={`/detalle?lic=${part}`}
            className="text-primary underline hover:no-underline"
          >
            {part}
          </a>
        );
      }
      return part;
    });
  }

  const showEmpty =
    !loading && !error && !searchResults && !askAnswer && !streaming;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
          <BookOpen className="h-7 w-7" />
          Investigador
        </h1>
        <p className="text-muted-foreground">
          Busqueda semantica RAG sobre el corpus de licitaciones.
        </p>
      </div>

      {/* ---- Configuration panel ---- */}
      <Card>
        <CardHeader
          className="cursor-pointer select-none py-3"
          onClick={() => setSettingsOpen((o) => !o)}
          tabIndex={0}
          role="button"
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSettingsOpen((o) => !o); } }}
        >
          <CardTitle className="text-sm flex items-center gap-2">
            <Settings className="h-4 w-4" />
            Configuracion
            {settingsOpen ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </CardTitle>
        </CardHeader>
        {settingsOpen && (
          <CardContent className="pt-0">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {/* top_k */}
              <div className="space-y-1">
                <label className="text-xs font-medium">
                  top_k: {config.topK}
                </label>
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
                <label className="text-xs font-medium">
                  Alpha (FAISS vs FTS5): {config.alpha.toFixed(2)}
                </label>
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
                <label className="text-xs font-medium">Modelo LLM</label>
                <Select value={config.model || "__default__"} onValueChange={(v) => updateConfig({ model: v === "__default__" ? "" : v })}>
                  <SelectTrigger>
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
                  onCheckedChange={(checked) =>
                    updateConfig({ useGlobalFilters: !!checked })
                  }
                  className="h-5 w-5"
                />
                <label
                  htmlFor="use-global-filters"
                  className="text-xs font-medium cursor-pointer"
                >
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
          <div className="flex gap-2 mb-4">
            <Button
              variant={mode === "search" ? "default" : "outline"}
              size="sm"
              onClick={() => setMode("search")}
            >
              <Search className="mr-2 h-4 w-4" />
              Busqueda
            </Button>
            <Button
              variant={mode === "ask" ? "default" : "outline"}
              size="sm"
              onClick={() => setMode("ask")}
            >
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
            <Button
              onClick={() => handleSubmit()}
              disabled={loading || !query.trim()}
            >
              {loading
                ? "Buscando..."
                : mode === "search"
                  ? "Buscar"
                  : "Preguntar"}
            </Button>
          </div>

          {/* History chips */}
          {history.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-3">
              <Clock className="h-4 w-4 text-muted-foreground mt-0.5" />
              {history.map((h) => (
                <Badge
                  key={h}
                  variant="secondary"
                  className="cursor-pointer hover:bg-accent"
                  role="button"
                  tabIndex={0}
                  onClick={() => {
                    setQuery(h);
                    handleSubmit(h);
                  }}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setQuery(h); handleSubmit(h); } }}
                >
                  {h}
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ---- Example question chips ---- */}
      {showEmpty && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Sparkles className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm text-muted-foreground font-medium">
              Preguntas de ejemplo
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {EXAMPLE_QUESTIONS.map((eq) => (
              <Badge
                key={eq}
                variant="outline"
                className="cursor-pointer hover:bg-accent px-3 py-1.5 text-sm"
                role="button"
                tabIndex={0}
                onClick={() => handleExampleClick(eq)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handleExampleClick(eq); } }}
              >
                {eq}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* ---- Loading ---- */}
      {loading && !streaming && (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <Card key={i}>
              <CardContent className="pt-6 space-y-2">
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

      {/* ---- Search results ---- */}
      {!loading && searchResults && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">
              {searchResults.length} resultados encontrados
            </h2>
            {searchResults.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => exportCSV(searchResults)}
              >
                <Download className="mr-2 h-4 w-4" />
                Exportar CSV
              </Button>
            )}
          </div>
          {searchResults.length === 0 ? (
            <Card className="border-dashed">
              <CardContent className="py-8 text-center text-muted-foreground">
                No se encontraron resultados para tu busqueda.
              </CardContent>
            </Card>
          ) : (
            searchResults.map((r, i) => {
              const organo =
                r.organo_contratacion ?? r.organo ?? "";
              const rid = r.id_externo ?? r.id ?? String(i);
              const excerpt = r.description
                ? truncate(r.description, 200)
                : null;

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
                      <div className="flex items-center gap-2 shrink-0">
                        {relevanceBadge(r.score)}
                        {r.score != null && (
                          <Badge variant="outline">
                            {(r.score * 100).toFixed(1)}%
                          </Badge>
                        )}
                      </div>
                    </div>
                    {organo && (
                      <CardDescription>{organo}</CardDescription>
                    )}
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {/* Context excerpt */}
                    {excerpt && (
                      <p className="text-sm text-muted-foreground">
                        {highlightQuery(excerpt, query)}
                      </p>
                    )}
                    <div className="flex items-center gap-4">
                      {r.importe != null && (
                        <Badge variant="secondary">
                          {formatCurrency(r.importe)}
                        </Badge>
                      )}
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

      {/* ---- Ask answer (streaming or static) ---- */}
      {(askAnswer != null || streaming) && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <MessageSquare className="h-4 w-4" />
                Respuesta
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="whitespace-pre-wrap text-sm font-sans leading-relaxed">
                {askAnswer ? renderAnswer(askAnswer) : ""}
                {streaming && (
                  <span className="animate-pulse text-primary">&#9612;</span>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* ---- Empty state (no example chips shown above already) ---- */}
      {showEmpty && (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <Search className="h-12 w-12 text-muted-foreground/50 mb-4" />
            <p className="text-lg font-medium text-muted-foreground">
              Introduce una consulta para buscar en el corpus de licitaciones
            </p>
            <p className="text-sm text-muted-foreground/70 mt-1">
              Usa el modo &quot;Busqueda&quot; para resultados semanticos o
              &quot;Preguntar&quot; para respuestas generativas.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
