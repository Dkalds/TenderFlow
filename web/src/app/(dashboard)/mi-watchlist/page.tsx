"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Eye,
  Plus,
  Trash2,
  Search,
  Star,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { cn, formatCurrency, formatDate, truncate } from "@/lib/utils";
import { getJSON, setJSON } from "@/lib/storage";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface WatchlistRule {
  id: string;
  keyword: string;
  cpvFilter: string;
  minImporte: number | null;
  ccaa: string;
  frequency: "inmediata" | "diaria" | "semanal";
  active: boolean;
  createdAt: string;
}

interface LicitacionItem {
  id_externo?: string;
  titulo?: string;
  organo_contratacion?: string;
  organo?: string;
  importe?: number;
  estado?: string;
  fecha_publicacion?: string;
  // Campos extra del backend que no modelamos explícitamente.
  [key: string]: unknown;
}

interface MatchedItem extends LicitacionItem {
  _matchedRules: string[]; // rule ids
}

/* ------------------------------------------------------------------ */
/*  Storage helpers                                                    */
/* ------------------------------------------------------------------ */

const STORAGE_KEY = "watchlist_rules";

function loadRules(): WatchlistRule[] {
  const parsed = getJSON<WatchlistRule[]>(STORAGE_KEY, []);
  return parsed.map((r) => ({
    ...r,
    ccaa: r.ccaa ?? "",
    frequency: r.frequency ?? "diaria",
    active: r.active ?? true,
  }));
}

function saveRules(rules: WatchlistRule[]) {
  setJSON(STORAGE_KEY, rules);
}

/* ------------------------------------------------------------------ */
/*  CCAA options (static fallback; ideally fetched from /api/v1/meta)  */
/* ------------------------------------------------------------------ */

const CCAA_OPTIONS = [
  "__all__",
  "Andalucia",
  "Aragon",
  "Asturias",
  "Baleares",
  "Canarias",
  "Cantabria",
  "Castilla y Leon",
  "Castilla-La Mancha",
  "Cataluna",
  "Ceuta",
  "Comunidad Valenciana",
  "Extremadura",
  "Galicia",
  "La Rioja",
  "Madrid",
  "Melilla",
  "Murcia",
  "Navarra",
  "Pais Vasco",
];

const FREQ_OPTIONS: { value: WatchlistRule["frequency"]; label: string }[] = [
  { value: "inmediata", label: "Inmediata" },
  { value: "diaria", label: "Diaria" },
  { value: "semanal", label: "Semanal" },
];

/* ------------------------------------------------------------------ */
/*  Page component                                                     */
/* ------------------------------------------------------------------ */

export default function MiWatchlistPage() {
  const [rules, setRules] = useState<WatchlistRule[]>([]);
  const [mounted, setMounted] = useState(false);

  // Form state
  const [keyword, setKeyword] = useState("");
  const [cpvFilter, setCpvFilter] = useState("");
  const [minImporte, setMinImporte] = useState("");
  const [ccaa, setCcaa] = useState("");
  const [frequency, setFrequency] =
    useState<WatchlistRule["frequency"]>("diaria");
  const [formOpen, setFormOpen] = useState(true);

  // Load persisted state after mount to avoid SSR hydration mismatch
  useEffect(() => {
    setRules(loadRules()); // eslint-disable-line react-hooks/set-state-in-effect
    setMounted(true);
  }, []);

  // Try to fetch CCAA options from backend (best-effort)
  const { data: metaCcaas } = useQuery<string[]>({
    queryKey: ["meta-ccaas"],
    queryFn: async () => {
      const res = await fetch("/api/v1/meta/filters", {
        credentials: "include",
      });
      if (!res.ok) return [];
      const data = await res.json();
      return (data.ccaas ?? data.ccaa ?? []) as string[];
    },
    staleTime: Infinity,
  });

  const ccaaList = metaCcaas && metaCcaas.length > 0 ? ["__all__", ...metaCcaas] : CCAA_OPTIONS;

  /* ---- Active rules ---- */
  const activeRules = useMemo(
    () => rules.filter((r) => r.active),
    [rules],
  );

  /* ---- Fetch matches for ALL active rules in parallel ---- */
  const { data: allMatches, isLoading: matchesLoading } = useQuery<
    MatchedItem[]
  >({
    queryKey: [
      "watchlist-matches",
      activeRules.map((r) => `${r.keyword}|${r.ccaa}`).join(","),
    ],
    queryFn: async () => {
      if (activeRules.length === 0) return [];

      const fetches = activeRules.map(async (rule) => {
        const params = new URLSearchParams();
        params.set("q", rule.keyword);
        if (rule.ccaa) params.set("ccaa", rule.ccaa);
        params.set("limit", "20");

        const res = await fetch(
          `/api/v1/licitaciones?${params.toString()}`,
          { credentials: "include" },
        );
        if (!res.ok) return { rule, items: [] as LicitacionItem[] };
        const data = await res.json();
        const items: LicitacionItem[] = data.items ?? data.results ?? [];
        return { rule, items };
      });

      const results = await Promise.all(fetches);

      // Merge + deduplicate by id_externo, track which rules matched
      const map = new Map<string, MatchedItem>();
      for (const { rule, items } of results) {
        for (const item of items) {
          // Client-side min importe filter
          if (
            rule.minImporte != null &&
            item.importe != null &&
            item.importe < rule.minImporte
          )
            continue;

          const key = item.id_externo ?? item.titulo ?? JSON.stringify(item);
          const existing = map.get(key);
          if (existing) {
            if (!existing._matchedRules.includes(rule.id)) {
              existing._matchedRules.push(rule.id);
            }
          } else {
            map.set(key, { ...item, _matchedRules: [rule.id] });
          }
        }
      }

      return Array.from(map.values());
    },
    enabled: activeRules.length > 0,
  });

  /* ---- Match counts per rule ---- */
  const matchCountByRule = useMemo(() => {
    const counts: Record<string, number> = {};
    if (allMatches) {
      for (const m of allMatches) {
        for (const rid of m._matchedRules) {
          counts[rid] = (counts[rid] ?? 0) + 1;
        }
      }
    }
    return counts;
  }, [allMatches]);

  /* ---- Rule CRUD ---- */
  const addRule = useCallback(() => {
    if (!keyword.trim()) return;
    const newRule: WatchlistRule = {
      id: crypto.randomUUID(),
      keyword: keyword.trim(),
      cpvFilter: cpvFilter.trim(),
      minImporte: minImporte ? parseFloat(minImporte) : null,
      ccaa,
      frequency,
      active: true,
      createdAt: new Date().toISOString(),
    };
    const updated = [...rules, newRule];
    setRules(updated);
    saveRules(updated);
    setKeyword("");
    setCpvFilter("");
    setMinImporte("");
    setCcaa("");
    setFrequency("diaria");
  }, [keyword, cpvFilter, minImporte, ccaa, frequency, rules]);

  const deleteRule = useCallback(
    (id: string) => {
      const updated = rules.filter((r) => r.id !== id);
      setRules(updated);
      saveRules(updated);
    },
    [rules],
  );

  const toggleRule = useCallback(
    (id: string) => {
      const updated = rules.map((r) =>
        r.id === id ? { ...r, active: !r.active } : r,
      );
      setRules(updated);
      saveRules(updated);
    },
    [rules],
  );

  const ruleNameById = useMemo(() => {
    const m: Record<string, string> = {};
    for (const r of rules) m[r.id] = r.keyword;
    return m;
  }, [rules]);

  /* ---------------------------------------------------------------- */
  /*  Render                                                           */
  /* ---------------------------------------------------------------- */

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
          <Star className="h-7 w-7" />
          Mi Watchlist
        </h1>
        <p className="text-muted-foreground">
          Reglas personalizadas de seguimiento de licitaciones.
        </p>
      </div>

      {/* ---- Add rule form ---- */}
      <Card>
        <CardHeader
          className="cursor-pointer select-none"
          onClick={() => setFormOpen((o) => !o)}
          tabIndex={0}
          role="button"
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setFormOpen((o) => !o); } }}
        >
          <CardTitle className="flex items-center gap-2">
            {formOpen ? (
              <ChevronDown className="h-5 w-5" />
            ) : (
              <ChevronRight className="h-5 w-5" />
            )}
            <Plus className="h-5 w-5" />
            Nueva regla de seguimiento
          </CardTitle>
          <CardDescription>
            Define criterios para recibir alertas sobre licitaciones relevantes.
          </CardDescription>
        </CardHeader>
        {formOpen && (
          <CardContent>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {/* Keyword */}
              <div className="space-y-1">
                <label htmlFor="wl-keyword" className="text-sm font-medium">Palabra clave *</label>
                <Input
                  id="wl-keyword"
                  placeholder="Ej: SAP, infraestructura..."
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addRule()}
                />
              </div>
              {/* CPV */}
              <div className="space-y-1">
                <label htmlFor="wl-cpv" className="text-sm font-medium">Filtro CPV</label>
                <Input
                  id="wl-cpv"
                  placeholder="Ej: 72000000"
                  value={cpvFilter}
                  onChange={(e) => setCpvFilter(e.target.value)}
                />
              </div>
              {/* Min importe */}
              <div className="space-y-1">
                <label htmlFor="wl-importe" className="text-sm font-medium">Importe minimo</label>
                <Input
                  id="wl-importe"
                  type="number"
                  placeholder="Ej: 100000"
                  value={minImporte}
                  onChange={(e) => setMinImporte(e.target.value)}
                />
              </div>
              {/* CCAA */}
              <div className="space-y-1">
                <label htmlFor="wl-ccaa" className="text-sm font-medium">
                  Comunidad Autonoma
                </label>
                <Select value={ccaa || "__all__"} onValueChange={(v) => setCcaa(v === "__all__" ? "" : v)}>
                  <SelectTrigger id="wl-ccaa">
                    <SelectValue placeholder="— Todas —" />
                  </SelectTrigger>
                  <SelectContent>
                    {ccaaList.map((c) => (
                      <SelectItem key={c} value={c}>
                        {c === "__all__" ? "— Todas —" : c}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {/* Frequency */}
              <div className="space-y-1">
                <label htmlFor="wl-frequency" className="text-sm font-medium">
                  Frecuencia de notificacion
                </label>
                <Select value={frequency} onValueChange={(v) => setFrequency(v as WatchlistRule["frequency"])}>
                  <SelectTrigger id="wl-frequency">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {FREQ_OPTIONS.map((f) => (
                      <SelectItem key={f.value} value={f.value}>
                        {f.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {/* Submit */}
              <div className="flex items-end">
                <Button
                  onClick={addRule}
                  disabled={!keyword.trim()}
                  className="w-full"
                >
                  <Plus className="mr-2 h-4 w-4" />
                  Agregar regla
                </Button>
              </div>
            </div>
          </CardContent>
        )}
      </Card>

      <Separator />

      {/* ---- Rules list ---- */}
      <div>
        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
          <Eye className="h-5 w-5" />
          Reglas ({rules.length})
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
              <Card
                key={rule.id}
                className={cn(!rule.active && "opacity-50")}
              >
                <CardHeader className="flex flex-row items-start justify-between pb-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <CardTitle className="text-base truncate">
                        {rule.keyword}
                      </CardTitle>
                      {matchCountByRule[rule.id] != null && (
                        <Badge variant="default" className="shrink-0">
                          {matchCountByRule[rule.id]}
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">
                      Creada: {formatDate(rule.createdAt)}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-9 w-9"
                      title={rule.active ? "Desactivar" : "Activar"}
                      onClick={() => toggleRule(rule.id)}
                    >
                      <Eye
                        className={cn(
                          "h-4 w-4",
                          rule.active
                            ? "text-primary"
                            : "text-muted-foreground",
                        )}
                      />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-9 w-9 text-destructive"
                      onClick={() => deleteRule(rule.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-2">
                  {rule.cpvFilter && (
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-muted-foreground">
                        CPV:
                      </span>
                      <Badge variant="outline">{rule.cpvFilter}</Badge>
                    </div>
                  )}
                  {rule.minImporte != null && (
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-muted-foreground">
                        Min:
                      </span>
                      <Badge variant="secondary">
                        {formatCurrency(rule.minImporte)}
                      </Badge>
                    </div>
                  )}
                  {rule.ccaa && (
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-muted-foreground">
                        CCAA:
                      </span>
                      <Badge variant="outline">{rule.ccaa}</Badge>
                    </div>
                  )}
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-muted-foreground">
                      Frecuencia:
                    </span>
                    <span className="text-sm capitalize">{rule.frequency}</span>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* ---- Match results section ---- */}
      {activeRules.length > 0 && (
        <>
          <Separator />
          <div>
            <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
              <Search className="h-5 w-5" />
              Resultados combinados
              {allMatches && (
                <Badge variant="secondary">{allMatches.length}</Badge>
              )}
            </h2>

            {matchesLoading ? (
              <div className="space-y-3">
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
            ) : allMatches && allMatches.length > 0 ? (
              <div className="space-y-2">
                {allMatches.map((item, i) => {
                  const organo =
                    item.organo_contratacion ?? item.organo ?? "";
                  const id = item.id_externo ?? String(i);
                  return (
                    <Card key={id} className="hover:bg-accent/30 transition-colors">
                      <CardContent className="py-3 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
                        {/* Title + organo */}
                        <div className="flex-1 min-w-0">
                          <a
                            href={`/detalle?lic=${item.id_externo ?? ""}`}
                            className="text-sm font-medium hover:underline line-clamp-1"
                          >
                            {truncate(item.titulo ?? "Sin titulo", 100)}
                          </a>
                          {organo && (
                            <p className="text-xs text-muted-foreground truncate">
                              {organo}
                            </p>
                          )}
                        </div>
                        {/* Importe */}
                        {item.importe != null && (
                          <Badge variant="secondary" className="shrink-0">
                            {formatCurrency(item.importe)}
                          </Badge>
                        )}
                        {/* Estado */}
                        {item.estado && (
                          <Badge variant="outline" className="shrink-0">
                            {item.estado}
                          </Badge>
                        )}
                        {/* Fecha */}
                        {item.fecha_publicacion && (
                          <span className="text-xs text-muted-foreground shrink-0">
                            {formatDate(item.fecha_publicacion)}
                          </span>
                        )}
                        {/* Matched rules */}
                        <div className="flex gap-1 shrink-0">
                          {item._matchedRules.map((rid) => (
                            <Badge
                              key={rid}
                              variant="default"
                              className="text-xs px-1.5"
                            >
                              {ruleNameById[rid] ?? "?"}
                            </Badge>
                          ))}
                        </div>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            ) : (
              <Card className="border-dashed">
                <CardContent className="py-8 text-center text-muted-foreground">
                  No se encontraron licitaciones que coincidan con tus reglas
                  activas.
                </CardContent>
              </Card>
            )}
          </div>
        </>
      )}
    </div>
  );
}
