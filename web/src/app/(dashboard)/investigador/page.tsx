"use client";

import { useState, useCallback } from "react";
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
import { Search, MessageSquare, Clock } from "lucide-react";
import { formatCurrency } from "@/lib/utils";

type Mode = "search" | "ask";

interface SearchResult {
  titulo?: string;
  organo?: string;
  importe?: number;
  score?: number;
  id?: string;
  expediente?: string;
}

interface SearchResponse {
  results?: SearchResult[];
  items?: SearchResult[];
}

interface AskResponse {
  answer?: string;
  sources?: SearchResult[];
}

export default function InvestigadorPage() {
  const [mode, setMode] = useState<Mode>("search");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);
  const [askAnswer, setAskAnswer] = useState<string | null>(null);
  const [askSources, setAskSources] = useState<SearchResult[] | null>(null);
  const [history, setHistory] = useState<string[]>([]);

  const handleSubmit = useCallback(async () => {
    const q = query.trim();
    if (!q) return;

    setLoading(true);
    setError(null);
    setSearchResults(null);
    setAskAnswer(null);
    setAskSources(null);

    // Update history
    setHistory((prev) => {
      const filtered = prev.filter((h) => h !== q);
      return [q, ...filtered].slice(0, 5);
    });

    try {
      if (mode === "search") {
        const res = await fetch("/api/v1/search", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: q, top_k: 10 }),
        });
        if (!res.ok) throw new Error(`Error ${res.status}`);
        const data: SearchResponse = await res.json();
        setSearchResults(data.results ?? data.items ?? []);
      } else {
        const res = await fetch("/api/v1/ask", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: q, top_k: 5 }),
        });
        if (!res.ok) throw new Error(`Error ${res.status}`);
        const data: AskResponse = await res.json();
        setAskAnswer(data.answer ?? "Sin respuesta disponible.");
        setAskSources(data.sources ?? []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desconocido");
    } finally {
      setLoading(false);
    }
  }, [query, mode]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Investigador</h1>
        <p className="text-muted-foreground">
          Busqueda semantica RAG sobre el corpus de licitaciones.
        </p>
      </div>

      {/* Search bar */}
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
            <Button onClick={handleSubmit} disabled={loading || !query.trim()}>
              {loading ? "Buscando..." : mode === "search" ? "Buscar" : "Preguntar"}
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
                  onClick={() => {
                    setQuery(h);
                  }}
                >
                  {h}
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Loading */}
      {loading && (
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

      {/* Error */}
      {error && (
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-destructive font-medium">Error: {error}</p>
          </CardContent>
        </Card>
      )}

      {/* Search results */}
      {!loading && searchResults && (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold">
            {searchResults.length} resultados encontrados
          </h2>
          {searchResults.length === 0 ? (
            <Card className="border-dashed">
              <CardContent className="py-8 text-center text-muted-foreground">
                No se encontraron resultados para tu busqueda.
              </CardContent>
            </Card>
          ) : (
            searchResults.map((r, i) => (
              <Card key={r.id ?? i}>
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-4">
                    <CardTitle className="text-base leading-snug">
                      {r.titulo ?? "Sin titulo"}
                    </CardTitle>
                    {r.score != null && (
                      <Badge variant="outline" className="shrink-0">
                        {(r.score * 100).toFixed(1)}%
                      </Badge>
                    )}
                  </div>
                  {r.organo && (
                    <CardDescription>{r.organo}</CardDescription>
                  )}
                </CardHeader>
                <CardContent className="flex items-center gap-4">
                  {r.importe != null && (
                    <Badge variant="secondary">
                      {formatCurrency(r.importe)}
                    </Badge>
                  )}
                  {(r.id || r.expediente) && (
                    <a
                      href={`/detalle?id=${r.id ?? r.expediente}`}
                      className="text-sm text-primary underline hover:no-underline"
                    >
                      Ver detalle
                    </a>
                  )}
                </CardContent>
              </Card>
            ))
          )}
        </div>
      )}

      {/* Ask answer */}
      {!loading && askAnswer && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <MessageSquare className="h-4 w-4" />
                Respuesta
              </CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="whitespace-pre-wrap text-sm font-sans leading-relaxed">
                {askAnswer}
              </pre>
            </CardContent>
          </Card>

          {askSources && askSources.length > 0 && (
            <>
              <Separator />
              <h3 className="text-sm font-semibold text-muted-foreground">
                Fuentes ({askSources.length})
              </h3>
              {askSources.map((s, i) => (
                <Card key={s.id ?? i}>
                  <CardContent className="pt-4 flex items-center justify-between gap-4">
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">
                        {s.titulo ?? "Sin titulo"}
                      </p>
                      {s.organo && (
                        <p className="text-xs text-muted-foreground truncate">
                          {s.organo}
                        </p>
                      )}
                    </div>
                    {s.importe != null && (
                      <Badge variant="secondary" className="shrink-0">
                        {formatCurrency(s.importe)}
                      </Badge>
                    )}
                  </CardContent>
                </Card>
              ))}
            </>
          )}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && !searchResults && !askAnswer && (
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
