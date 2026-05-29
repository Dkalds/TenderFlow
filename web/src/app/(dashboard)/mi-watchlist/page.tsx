"use client";

import { useState, useEffect, useCallback } from "react";
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
import { Eye, Plus, Trash2, Search } from "lucide-react";
import { formatCurrency, formatDate } from "@/lib/utils";

interface WatchlistRule {
  id: string;
  keyword: string;
  cpvFilter: string;
  minImporte: number | null;
  createdAt: string;
}

const STORAGE_KEY = "licitaciones-watchlist-rules";

function loadRules(): WatchlistRule[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveRules(rules: WatchlistRule[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(rules));
}

export default function MiWatchlistPage() {
  const [rules, setRules] = useState<WatchlistRule[]>([]);
  const [keyword, setKeyword] = useState("");
  const [cpvFilter, setCpvFilter] = useState("");
  const [minImporte, setMinImporte] = useState("");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setRules(loadRules());
    setMounted(true);
  }, []);

  const activeRule = rules[0];

  const { data: results, isLoading: resultsLoading } = useQuery({
    queryKey: ["watchlist-results", activeRule?.keyword],
    queryFn: async () => {
      if (!activeRule?.keyword) return null;
      const res = await fetch(
        `/api/v1/licitaciones?q=${encodeURIComponent(activeRule.keyword)}`,
        { credentials: "include" }
      );
      if (!res.ok) throw new Error("Error fetching results");
      return res.json();
    },
    enabled: !!activeRule?.keyword,
  });

  const addRule = useCallback(() => {
    if (!keyword.trim()) return;
    const newRule: WatchlistRule = {
      id: crypto.randomUUID(),
      keyword: keyword.trim(),
      cpvFilter: cpvFilter.trim(),
      minImporte: minImporte ? parseFloat(minImporte) : null,
      createdAt: new Date().toISOString(),
    };
    const updated = [...rules, newRule];
    setRules(updated);
    saveRules(updated);
    setKeyword("");
    setCpvFilter("");
    setMinImporte("");
  }, [keyword, cpvFilter, minImporte, rules]);

  const deleteRule = useCallback(
    (id: string) => {
      const updated = rules.filter((r) => r.id !== id);
      setRules(updated);
      saveRules(updated);
    },
    [rules]
  );

  const matchCount =
    results && Array.isArray(results.items)
      ? results.items.length
      : results && typeof results.total === "number"
        ? results.total
        : null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Mi Watchlist</h1>
        <p className="text-muted-foreground">
          Reglas personalizadas de seguimiento de licitaciones.
        </p>
      </div>

      {/* Add rule form */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Plus className="h-5 w-5" />
            Nueva regla de seguimiento
          </CardTitle>
          <CardDescription>
            Define criterios para recibir alertas sobre licitaciones relevantes.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-1">
              <label className="text-sm font-medium">Palabra clave *</label>
              <Input
                placeholder="Ej: SAP, infraestructura..."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addRule()}
              />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Filtro CPV</label>
              <Input
                placeholder="Ej: 72000000"
                value={cpvFilter}
                onChange={(e) => setCpvFilter(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium">Importe minimo</label>
              <Input
                type="number"
                placeholder="Ej: 100000"
                value={minImporte}
                onChange={(e) => setMinImporte(e.target.value)}
              />
            </div>
            <div className="flex items-end">
              <Button onClick={addRule} disabled={!keyword.trim()} className="w-full">
                <Plus className="mr-2 h-4 w-4" />
                Agregar regla
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Separator />

      {/* Rules list */}
      <div>
        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
          <Eye className="h-5 w-5" />
          Reglas activas
        </h2>

        {!mounted ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {[1, 2].map((i) => (
              <Card key={i}>
                <CardContent className="pt-6">
                  <Skeleton className="h-6 w-32 mb-2" />
                  <Skeleton className="h-4 w-48" />
                </CardContent>
              </Card>
            ))}
          </div>
        ) : rules.length === 0 ? (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center justify-center py-12 text-center">
              <Eye className="h-12 w-12 text-muted-foreground/50 mb-4" />
              <p className="text-lg font-medium text-muted-foreground">
                No tienes reglas de seguimiento configuradas
              </p>
              <p className="text-sm text-muted-foreground/70 mt-1">
                Usa el formulario de arriba para crear tu primera regla.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {rules.map((rule) => (
              <Card key={rule.id}>
                <CardHeader className="flex flex-row items-start justify-between pb-2">
                  <div>
                    <CardTitle className="text-base">{rule.keyword}</CardTitle>
                    <p className="text-xs text-muted-foreground mt-1">
                      Creada: {formatDate(rule.createdAt)}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-destructive"
                    onClick={() => deleteRule(rule.id)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </CardHeader>
                <CardContent className="space-y-2">
                  {rule.cpvFilter && (
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-muted-foreground">CPV:</span>
                      <Badge variant="outline">{rule.cpvFilter}</Badge>
                    </div>
                  )}
                  {rule.minImporte != null && (
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-muted-foreground">Min importe:</span>
                      <Badge variant="secondary">
                        {formatCurrency(rule.minImporte)}
                      </Badge>
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* Results for first active rule */}
      {activeRule && (
        <>
          <Separator />
          <div>
            <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
              <Search className="h-5 w-5" />
              Resultados para &quot;{activeRule.keyword}&quot;
            </h2>
            {resultsLoading ? (
              <Card>
                <CardContent className="pt-6">
                  <Skeleton className="h-6 w-48 mb-2" />
                  <Skeleton className="h-4 w-32" />
                </CardContent>
              </Card>
            ) : matchCount != null ? (
              <Card>
                <CardContent className="pt-6">
                  <p className="text-2xl font-bold">{matchCount}</p>
                  <p className="text-sm text-muted-foreground">
                    licitaciones encontradas que coinciden con tu regla
                  </p>
                </CardContent>
              </Card>
            ) : (
              <Card>
                <CardContent className="pt-6">
                  <p className="text-sm text-muted-foreground">
                    No se pudieron cargar los resultados.
                  </p>
                </CardContent>
              </Card>
            )}
          </div>
        </>
      )}
    </div>
  );
}
