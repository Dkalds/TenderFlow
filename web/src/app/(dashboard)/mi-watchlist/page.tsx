"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
import {
  useRemoveWatchlistItem,
  useWatchlistItems,
} from "@/hooks/use-watchlist-items";

/* ------------------------------------------------------------------ */
/*  Types — alineados con /api/v1/watchlist/rules                      */
/* ------------------------------------------------------------------ */

type Frequency = "immediate" | "daily" | "weekly";

interface ApiRule {
  id: number;
  nombre: string | null;
  keyword: string | null;
  cpv: string | null;
  min_importe: number | null;
  ccaa: string | null;
  frequency: Frequency;
  active: boolean;
  match_count: number;
}

interface RuleBody {
  nombre: string | null;
  keyword: string | null;
  cpv: string | null;
  min_importe: number | null;
  ccaa: string | null;
  frequency: Frequency;
  active: boolean;
}

interface MatchItem {
  id_externo?: string;
  titulo?: string;
  organo_contratacion?: string;
  importe?: number;
  estado?: string;
  fecha_publicacion?: string;
  [key: string]: unknown;
}

/* ------------------------------------------------------------------ */
/*  Helpers de API (sesión vía cookie, igual que el resto del dash)    */
/* ------------------------------------------------------------------ */

const RULES_KEY = "/api/v1/watchlist/rules";

async function apiSend(
  method: string,
  url: string,
  body?: unknown,
): Promise<unknown> {
  const res = await fetch(url, {
    method,
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json().catch(() => null);
}

function ruleToBody(rule: ApiRule, overrides: Partial<RuleBody> = {}): RuleBody {
  return {
    nombre: rule.nombre,
    keyword: rule.keyword,
    cpv: rule.cpv,
    min_importe: rule.min_importe,
    ccaa: rule.ccaa,
    frequency: rule.frequency,
    active: rule.active,
    ...overrides,
  };
}

/* ------------------------------------------------------------------ */
/*  Migración one-shot del localStorage legacy → servidor             */
/* ------------------------------------------------------------------ */

const LEGACY_KEY = "watchlist_rules";
const MIGRATED_FLAG = "watchlist_rules_migrated";

interface LegacyRule {
  keyword?: string;
  cpvFilter?: string;
  minImporte?: number | null;
  ccaa?: string;
  frequency?: "inmediata" | "diaria" | "semanal";
  active?: boolean;
}

const LEGACY_FREQ: Record<string, Frequency> = {
  inmediata: "immediate",
  diaria: "daily",
  semanal: "weekly",
};

function legacyToBody(r: LegacyRule): RuleBody {
  return {
    nombre: r.keyword?.trim() || null,
    keyword: r.keyword?.trim() || null,
    cpv: r.cpvFilter?.trim() || null,
    min_importe: r.minImporte ?? null,
    ccaa: r.ccaa || null,
    frequency: LEGACY_FREQ[r.frequency ?? "diaria"] ?? "daily",
    active: r.active ?? true,
  };
}

/* ------------------------------------------------------------------ */
/*  Opciones de formulario                                             */
/* ------------------------------------------------------------------ */

const CCAA_FALLBACK = [
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

const FREQ_OPTIONS: { value: Frequency; label: string }[] = [
  { value: "immediate", label: "Inmediata" },
  { value: "daily", label: "Diaria" },
  { value: "weekly", label: "Semanal" },
];

const FREQ_LABEL: Record<Frequency, string> = {
  immediate: "Inmediata",
  daily: "Diaria",
  weekly: "Semanal",
};

/* ------------------------------------------------------------------ */
/*  Favoritos (licitaciones individuales, server-side)                 */
/* ------------------------------------------------------------------ */

function FavoritosPanel() {
  const { data: items, isLoading } = useWatchlistItems();
  const removeItem = useRemoveWatchlistItem();

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <Card key={i}>
            <CardContent className="pt-6 space-y-2">
              <Skeleton className="h-5 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  if (!items || items.length === 0) {
    return (
      <Card className="border-dashed">
        <CardContent className="flex flex-col items-center justify-center py-12 text-center">
          <Star className="h-12 w-12 text-muted-foreground/50 mb-4" />
          <p className="text-lg font-medium text-muted-foreground">
            No tienes licitaciones marcadas como favoritas
          </p>
          <p className="text-sm text-muted-foreground/70 mt-1">
            Marca licitaciones con la estrella desde la tabla de Detalle.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-2">
      {items.map((item) => (
        <Card key={item.id_externo} className="hover:bg-accent/30 transition-colors">
          <CardContent className="py-3 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
            <div className="flex-1 min-w-0">
              <a
                href={`/detalle?lic=${item.id_externo}`}
                className="text-sm font-medium hover:underline line-clamp-1"
              >
                {truncate(item.titulo ?? item.id_externo, 100)}
              </a>
            </div>
            {item.importe != null && (
              <Badge variant="secondary" className="shrink-0">
                {formatCurrency(item.importe)}
              </Badge>
            )}
            {item.estado && (
              <Badge variant="outline" className="shrink-0">
                {item.estado}
              </Badge>
            )}
            {item.fecha_publicacion && (
              <span className="text-xs text-muted-foreground shrink-0">
                {formatDate(item.fecha_publicacion)}
              </span>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9 shrink-0 text-destructive"
              title="Quitar de favoritos"
              onClick={() => removeItem.mutate(item.id_externo)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Página                                                             */
/* ------------------------------------------------------------------ */

export default function MiWatchlistPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"reglas" | "favoritos">("reglas");

  // Form state
  const [keyword, setKeyword] = useState("");
  const [cpv, setCpv] = useState("");
  const [minImporte, setMinImporte] = useState("");
  const [ccaa, setCcaa] = useState("");
  const [frequency, setFrequency] = useState<Frequency>("daily");
  const [formOpen, setFormOpen] = useState(true);

  /* ---- Reglas (server-side) ---- */
  const {
    data: rules,
    isLoading: rulesLoading,
  } = useQuery<ApiRule[]>({
    queryKey: ["watchlist-rules"],
    queryFn: async () => {
      const data = (await apiSend("GET", RULES_KEY)) as { items?: ApiRule[] };
      return data.items ?? [];
    },
  });

  /* ---- Migración one-shot del localStorage ---- */
  const migratedRef = useRef(false);
  useEffect(() => {
    if (migratedRef.current) return;
    migratedRef.current = true;
    if (getJSON<boolean>(MIGRATED_FLAG, false)) return;
    const legacy = getJSON<LegacyRule[]>(LEGACY_KEY, []);
    if (legacy.length === 0) {
      setJSON(MIGRATED_FLAG, true);
      return;
    }
    void (async () => {
      for (const r of legacy) {
        try {
          await apiSend("POST", RULES_KEY, legacyToBody(r));
        } catch {
          // best-effort: si una regla falla, seguimos con las demás
        }
      }
      setJSON(MIGRATED_FLAG, true);
      setJSON(LEGACY_KEY, []);
      qc.invalidateQueries({ queryKey: ["watchlist-rules"] });
    })();
  }, [qc]);

  /* ---- CCAA options (best-effort desde meta) ---- */
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
  const ccaaList =
    metaCcaas && metaCcaas.length > 0 ? ["__all__", ...metaCcaas] : CCAA_FALLBACK;

  /* ---- Mutations ---- */
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["watchlist-rules"] });

  const createMut = useMutation({
    mutationFn: (body: RuleBody) => apiSend("POST", RULES_KEY, body),
    onSuccess: invalidate,
  });
  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: RuleBody }) =>
      apiSend("PUT", `${RULES_KEY}/${id}`, body),
    onSuccess: invalidate,
  });
  const deleteMut = useMutation({
    mutationFn: (id: number) => apiSend("DELETE", `${RULES_KEY}/${id}`),
    onSuccess: invalidate,
  });

  const submit = () => {
    if (!keyword.trim()) return;
    createMut.mutate({
      nombre: keyword.trim(),
      keyword: keyword.trim(),
      cpv: cpv.trim() || null,
      min_importe: minImporte ? parseFloat(minImporte) : null,
      ccaa: ccaa || null,
      frequency,
      active: true,
    });
    setKeyword("");
    setCpv("");
    setMinImporte("");
    setCcaa("");
    setFrequency("daily");
  };

  const activeRules = useMemo(
    () => (rules ?? []).filter((r) => r.active),
    [rules],
  );

  /* ---- Resultados combinados (matches reales por regla activa) ---- */
  const { data: combined, isLoading: matchesLoading } = useQuery<MatchItem[]>({
    queryKey: ["watchlist-combined", activeRules.map((r) => r.id).join(",")],
    enabled: activeRules.length > 0,
    queryFn: async () => {
      const perRule = await Promise.all(
        activeRules.map(async (rule) => {
          try {
            const data = (await apiSend(
              "GET",
              `${RULES_KEY}/${rule.id}/matches?limit=20`,
            )) as { items?: MatchItem[] };
            return data.items ?? [];
          } catch {
            return [];
          }
        }),
      );
      const seen = new Map<string, MatchItem>();
      for (const items of perRule) {
        for (const item of items) {
          const key = item.id_externo ?? item.titulo ?? JSON.stringify(item);
          if (!seen.has(key)) seen.set(key, item);
        }
      }
      return Array.from(seen.values());
    },
  });

  const ruleCount = rules?.length ?? 0;

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
          Reglas de seguimiento guardadas en tu cuenta: el conteo de coincidencias
          es real (sobre todo el dataset) y las alertas por frecuencia se envían
          desde el servidor.
        </p>
      </div>

      {/* Tabs: reglas de criterio vs. licitaciones individuales marcadas */}
      <div className="inline-flex rounded-lg border border-border/70 p-1" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "reglas"}
          onClick={() => setTab("reglas")}
          className={cn(
            "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
            tab === "reglas"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          Reglas
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "favoritos"}
          onClick={() => setTab("favoritos")}
          className={cn(
            "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
            tab === "favoritos"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          Favoritos
        </button>
      </div>

      {tab === "favoritos" ? (
        <FavoritosPanel />
      ) : (
        <>
      {/* Add rule form */}
      <Card>
        <CardHeader
          className="cursor-pointer select-none"
          onClick={() => setFormOpen((o) => !o)}
          tabIndex={0}
          role="button"
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              setFormOpen((o) => !o);
            }
          }}
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
              <div className="space-y-1">
                <label htmlFor="wl-keyword" className="text-sm font-medium">
                  Palabra clave *
                </label>
                <Input
                  id="wl-keyword"
                  placeholder="Ej: SAP, infraestructura..."
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && submit()}
                />
              </div>
              <div className="space-y-1">
                <label htmlFor="wl-cpv" className="text-sm font-medium">
                  Filtro CPV
                </label>
                <Input
                  id="wl-cpv"
                  placeholder="Ej: 72000000"
                  value={cpv}
                  onChange={(e) => setCpv(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <label htmlFor="wl-importe" className="text-sm font-medium">
                  Importe minimo
                </label>
                <Input
                  id="wl-importe"
                  type="number"
                  placeholder="Ej: 100000"
                  value={minImporte}
                  onChange={(e) => setMinImporte(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <label htmlFor="wl-ccaa" className="text-sm font-medium">
                  Comunidad Autonoma
                </label>
                <Select
                  value={ccaa || "__all__"}
                  onValueChange={(v) => setCcaa(v === "__all__" ? "" : v)}
                >
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
              <div className="space-y-1">
                <label htmlFor="wl-frequency" className="text-sm font-medium">
                  Frecuencia de notificacion
                </label>
                <Select
                  value={frequency}
                  onValueChange={(v) => setFrequency(v as Frequency)}
                >
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
              <div className="flex items-end">
                <Button
                  onClick={submit}
                  disabled={!keyword.trim() || createMut.isPending}
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

      {/* Rules list */}
      <div>
        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
          <Eye className="h-5 w-5" />
          Reglas ({ruleCount})
        </h2>

        {rulesLoading ? (
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
        ) : ruleCount === 0 ? (
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
            {(rules ?? []).map((rule) => (
              <Card key={rule.id} className={cn(!rule.active && "opacity-50")}>
                <CardHeader className="flex flex-row items-start justify-between pb-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <CardTitle className="text-base truncate">
                        {rule.nombre || rule.keyword || "Regla"}
                      </CardTitle>
                      <Badge variant="default" className="shrink-0">
                        {rule.match_count}
                      </Badge>
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-9 w-9"
                      title={rule.active ? "Desactivar" : "Activar"}
                      onClick={() =>
                        updateMut.mutate({
                          id: rule.id,
                          body: ruleToBody(rule, { active: !rule.active }),
                        })
                      }
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
                      title="Eliminar"
                      onClick={() => deleteMut.mutate(rule.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-2">
                  {rule.keyword && (
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-muted-foreground">
                        Keyword:
                      </span>
                      <Badge variant="outline">{rule.keyword}</Badge>
                    </div>
                  )}
                  {rule.cpv && (
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-muted-foreground">CPV:</span>
                      <Badge variant="outline">{rule.cpv}</Badge>
                    </div>
                  )}
                  {rule.min_importe != null && (
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-muted-foreground">Min:</span>
                      <Badge variant="secondary">
                        {formatCurrency(rule.min_importe)}
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
                    <span className="text-sm">{FREQ_LABEL[rule.frequency]}</span>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* Combined matches */}
      {activeRules.length > 0 && (
        <>
          <Separator />
          <div>
            <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
              <Search className="h-5 w-5" />
              Resultados combinados
              {combined && <Badge variant="secondary">{combined.length}</Badge>}
            </h2>

            {matchesLoading ? (
              <div className="space-y-3">
                {[1, 2, 3].map((i) => (
                  <Card key={i}>
                    <CardContent className="pt-6 space-y-2">
                      <Skeleton className="h-5 w-3/4" />
                      <Skeleton className="h-4 w-1/2" />
                    </CardContent>
                  </Card>
                ))}
              </div>
            ) : combined && combined.length > 0 ? (
              <div className="space-y-2">
                {combined.map((item, i) => {
                  const id = item.id_externo ?? String(i);
                  return (
                    <Card
                      key={id}
                      className="hover:bg-accent/30 transition-colors"
                    >
                      <CardContent className="py-3 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
                        <div className="flex-1 min-w-0">
                          <a
                            href={`/detalle?lic=${item.id_externo ?? ""}`}
                            className="text-sm font-medium hover:underline line-clamp-1"
                          >
                            {truncate(item.titulo ?? "Sin titulo", 100)}
                          </a>
                          {item.organo_contratacion && (
                            <p className="text-xs text-muted-foreground truncate">
                              {item.organo_contratacion}
                            </p>
                          )}
                        </div>
                        {item.importe != null && (
                          <Badge variant="secondary" className="shrink-0">
                            {formatCurrency(item.importe)}
                          </Badge>
                        )}
                        {item.estado && (
                          <Badge variant="outline" className="shrink-0">
                            {item.estado}
                          </Badge>
                        )}
                        {item.fecha_publicacion && (
                          <span className="text-xs text-muted-foreground shrink-0">
                            {formatDate(item.fecha_publicacion)}
                          </span>
                        )}
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
        </>
      )}
    </div>
  );
}
