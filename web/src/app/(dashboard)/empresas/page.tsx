"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatCurrency, formatNumber, truncate } from "@/lib/utils";
import {
  Briefcase,
  Check,
  Eye,
  EyeOff,
  Handshake,
  Minus,
  Percent,
  Search,
  ShieldQuestion,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import { useDebounce } from "@/hooks/use-debounce";

/* ------------------------------------------------------------------ */
/*  Types (espejo de /api/v1/empresas y /api/v1/competitive)           */
/* ------------------------------------------------------------------ */

interface EmpresaRow {
  empresa_id: number;
  nombre_canonico: string;
  nif_canonico: string | null;
  es_ute: number;
  es_pyme: number | null;
  grupo: string | null;
  n_adjudicaciones: number;
  importe_total: number;
}

interface EmpresaStats {
  adjudicaciones_total: number;
  adjudicaciones_enlazadas: number;
  pct_filas: number;
  pct_importe: number;
  empresas: number;
  revisiones_pendientes: number;
}

interface EmpresaDetail {
  empresa_id: number;
  nombre_canonico: string;
  nif_canonico: string | null;
  es_ute: number;
  grupo: string | null;
  aliases: { alias_normalizado: string; nif_variante: string | null; fuente: string }[];
  ute_miembros: { empresa_id: number; nombre_canonico: string }[];
  participa_en_utes: { empresa_id: number; nombre_canonico: string }[];
}

interface PerfilEmpresa {
  totales: {
    contratos: number;
    importe_total: number;
    ofertas_medias: number | null;
    primera_adjudicacion: string | null;
    ultima_adjudicacion: string | null;
  };
  por_cpv: { cpv2: string; contratos: number; importe: number }[];
  por_ccaa: { ccaa: string; contratos: number; importe: number }[];
  organos_principales: { organo: string; contratos: number; importe: number }[];
  por_anio?: { anio: number; contratos: number; importe: number }[];
}

interface WatchlistItem {
  empresa_id: number;
  nombre_canonico: string;
  frequency: string;
}

interface ReviewItem {
  id: number;
  nombre_original: string;
  nif: string | null;
  score: number;
  candidato_empresa_id: number | null;
  candidato_nombre: string | null;
  candidato_nif: string | null;
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function EmpresasPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  // Deep-link desde los grafos (Ecosistema Partners / Red Órgano-Empresa):
  // `?q=<empresa>` siembra la búsqueda.
  const [search, setSearch] = useState(() => searchParams?.get("q") ?? "");
  const debouncedSearch = useDebounce(search, 300);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const { data: stats } = useQuery<EmpresaStats>({
    queryKey: ["empresas-stats"],
    queryFn: () => fetchWithAuth("/api/v1/empresas/stats"),
    staleTime: 5 * 60 * 1000,
  });

  const { data: list, isLoading } = useQuery<{ items: EmpresaRow[] }>({
    queryKey: ["empresas", debouncedSearch],
    queryFn: () =>
      fetchWithAuth(
        `/api/v1/empresas?limit=50${debouncedSearch ? `&q=${encodeURIComponent(debouncedSearch)}` : ""}`,
      ),
    staleTime: 60 * 1000,
  });

  const { data: watchlist } = useQuery<{ items: WatchlistItem[] }>({
    queryKey: ["watchlist-empresas"],
    queryFn: () => fetchWithAuth("/api/v1/competitive/watchlist"),
    staleTime: 60 * 1000,
  });
  const watchedIds = useMemo(
    () => new Set((watchlist?.items ?? []).map((w) => w.empresa_id)),
    [watchlist],
  );

  const toggleWatch = useMutation({
    mutationFn: async (empresa: { empresa_id: number; watched: boolean }) =>
      empresa.watched
        ? apiMutate("DELETE", `/api/v1/competitive/watchlist/${empresa.empresa_id}`)
        : apiMutate("POST", "/api/v1/competitive/watchlist", {
            empresa_id: empresa.empresa_id,
            frequency: "daily",
          }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["watchlist-empresas"] }),
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Empresas</h1>
        <p className="text-muted-foreground">
          Maestro de empresas canónicas: cada adjudicatario resuelto a una única entidad
          (NIF + aliases + UTEs).
        </p>
      </div>

      {/* KPIs de cobertura del maestro */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Empresas canónicas"
          value={stats ? formatNumber(stats.empresas) : "…"}
          icon={Briefcase}
        />
        <KpiCard
          title="Importe resuelto"
          value={stats ? `${stats.pct_importe.toFixed(1)}%` : "…"}
          subtitle={
            stats
              ? `${formatNumber(stats.adjudicaciones_enlazadas)} de ${formatNumber(stats.adjudicaciones_total)} adjudicaciones`
              : undefined
          }
          icon={Percent}
        />
        <KpiCard
          title="Vigiladas"
          value={watchlist ? formatNumber(watchlist.items.length) : "…"}
          icon={Eye}
        />
        <KpiCard
          title="Revisiones pendientes"
          value={stats ? formatNumber(stats.revisiones_pendientes) : "…"}
          icon={ShieldQuestion}
        />
      </div>

      {(stats?.revisiones_pendientes ?? 0) > 0 && <ReviewQueue />}

      {/* Buscador + tabla */}
      <Card>
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>Buscador</CardTitle>
            <CardDescription>
              Por nombre canónico, alias o NIF. Ordenado por importe adjudicado total.
            </CardDescription>
          </div>
          <div className="relative w-full sm:w-80">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Indra, B28599033, accenture…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8"
            />
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[320px] w-full" />
          ) : (list?.items ?? []).length === 0 ? (
            <EmptyState
              icon={Search}
              title="Sin resultados"
              hint="Prueba con otro nombre o NIF, o ejecuta el backfill del maestro."
            />
          ) : (
            <div className="max-h-[420px] overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Empresa</TableHead>
                    <TableHead>NIF</TableHead>
                    <TableHead className="text-right">Contratos</TableHead>
                    <TableHead className="text-right">Importe total</TableHead>
                    <TableHead className="w-24 text-right">Vigilar</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(list?.items ?? []).map((e) => {
                    const watched = watchedIds.has(e.empresa_id);
                    return (
                      <TableRow
                        key={e.empresa_id}
                        className={
                          selectedId === e.empresa_id
                            ? "cursor-pointer bg-primary/5"
                            : "cursor-pointer"
                        }
                        onClick={() => setSelectedId(e.empresa_id)}
                      >
                        <TableCell className="max-w-[300px]">
                          <div className="flex items-center gap-1.5">
                            <span className="truncate text-sm font-medium">
                              {e.nombre_canonico}
                            </span>
                            {e.es_ute ? <Badge variant="outline">UTE</Badge> : null}
                            {e.es_pyme ? <Badge variant="secondary">PYME</Badge> : null}
                          </div>
                        </TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground">
                          {e.nif_canonico ?? "—"}
                        </TableCell>
                        <TableCell className="text-right text-sm">
                          {formatNumber(e.n_adjudicaciones)}
                        </TableCell>
                        <TableCell className="text-right text-sm font-medium">
                          {formatCurrency(e.importe_total)}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={watched ? "Dejar de vigilar" : "Vigilar empresa"}
                            disabled={toggleWatch.isPending}
                            onClick={(ev) => {
                              ev.stopPropagation();
                              toggleWatch.mutate({ empresa_id: e.empresa_id, watched });
                            }}
                          >
                            {watched ? (
                              <Eye className="h-4 w-4 text-primary" />
                            ) : (
                              <EyeOff className="h-4 w-4 text-muted-foreground" />
                            )}
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {selectedId != null && <EmpresaPerfil empresaId={selectedId} />}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Perfil de empresa seleccionada                                     */
/* ------------------------------------------------------------------ */

function EmpresaPerfil({ empresaId }: { empresaId: number }) {
  const { data: detail } = useQuery<EmpresaDetail>({
    queryKey: ["empresa-detail", empresaId],
    queryFn: () => fetchWithAuth(`/api/v1/empresas/${empresaId}`),
  });

  const { data: perfil, isLoading } = useQuery<PerfilEmpresa>({
    queryKey: ["empresa-perfil", empresaId],
    queryFn: () => fetchWithAuth(`/api/v1/competitive/empresas/${empresaId}/perfil`),
  });

  if (isLoading || !detail) {
    return <Skeleton className="h-[380px] w-full" />;
  }

  const totales = perfil?.totales;

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle>{detail.nombre_canonico}</CardTitle>
          {detail.es_ute ? <Badge variant="outline">UTE</Badge> : null}
          {detail.grupo && <Badge variant="secondary">Grupo {detail.grupo}</Badge>}
        </div>
        <CardDescription className="font-mono">
          {detail.nif_canonico ?? "Sin NIF canónico"}
          {totales?.primera_adjudicacion &&
            ` · activa de ${totales.primera_adjudicacion.slice(0, 10)} a ${totales.ultima_adjudicacion?.slice(0, 10) ?? "hoy"}`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Totales */}
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <p className="text-xs font-medium uppercase text-muted-foreground">Contratos</p>
            <p className="font-mono text-xl font-bold">
              {formatNumber(totales?.contratos ?? 0)}
            </p>
          </div>
          <div>
            <p className="text-xs font-medium uppercase text-muted-foreground">
              Importe adjudicado
            </p>
            <p className="font-mono text-xl font-bold">
              {formatCurrency(totales?.importe_total ?? 0)}
            </p>
          </div>
          <div>
            <p className="text-xs font-medium uppercase text-muted-foreground">
              Ofertas medias (presión)
            </p>
            <p className="font-mono text-xl font-bold">{totales?.ofertas_medias ?? "—"}</p>
          </div>
        </div>

        <Separator />

        {/* Trayectoria temporal: ¿crece o decae? (señal competitiva) */}
        {(perfil?.por_anio?.length ?? 0) > 0 && (
          <>
            <YearTrend rows={perfil!.por_anio!} />
            <Separator />
          </>
        )}

        {/* Desgloses */}
        <div className="grid gap-6 lg:grid-cols-3">
          <MiniRanking
            title="Por familia CPV"
            rows={(perfil?.por_cpv ?? []).map((r) => ({
              label: `CPV ${r.cpv2}`,
              contratos: r.contratos,
              importe: r.importe,
            }))}
          />
          <MiniRanking
            title="Por territorio"
            rows={(perfil?.por_ccaa ?? []).map((r) => ({
              label: r.ccaa,
              contratos: r.contratos,
              importe: r.importe,
            }))}
          />
          <MiniRanking
            title="Órganos principales"
            rows={(perfil?.organos_principales ?? []).map((r) => ({
              label: truncate(r.organo, 38),
              contratos: r.contratos,
              importe: r.importe,
            }))}
          />
        </div>

        {/* UTEs y aliases */}
        {(detail.ute_miembros.length > 0 ||
          detail.participa_en_utes.length > 0 ||
          detail.aliases.length > 1) && (
          <>
            <Separator />
            <div className="grid gap-6 lg:grid-cols-2">
              {detail.ute_miembros.length > 0 && (
                <div>
                  <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
                    <Handshake className="h-4 w-4" /> Miembros de la UTE
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {detail.ute_miembros.map((m) => (
                      <Badge key={m.empresa_id} variant="secondary">
                        {m.nombre_canonico}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
              {detail.participa_en_utes.length > 0 && (
                <div>
                  <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
                    <Handshake className="h-4 w-4" /> Participa en UTEs
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {detail.participa_en_utes.map((u) => (
                      <Badge key={u.empresa_id} variant="secondary">
                        {u.nombre_canonico}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
              {detail.aliases.length > 1 && (
                <div>
                  <h3 className="mb-2 text-sm font-semibold">
                    Aliases vistos en fuente ({detail.aliases.length})
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {detail.aliases.slice(0, 12).map((a, i) => (
                      <Badge key={i} variant="outline" className="font-normal">
                        {a.alias_normalizado}
                      </Badge>
                    ))}
                    {detail.aliases.length > 12 && (
                      <span className="text-xs text-muted-foreground">
                        +{detail.aliases.length - 12} más
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function MiniRanking({
  title,
  rows,
}: {
  title: string;
  rows: { label: string; contratos: number; importe: number }[];
}) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Sin datos.</p>
      ) : (
        <ul className="space-y-1.5">
          {rows.slice(0, 6).map((r) => (
            <li key={r.label} className="flex items-center justify-between gap-2 text-sm">
              <span className="truncate">{r.label}</span>
              <span className="shrink-0 font-mono text-xs text-muted-foreground">
                {formatNumber(r.contratos)} · {formatCurrency(r.importe)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* Trayectoria temporal de la empresa: barras por año (orden cronológico) y un
   indicador de tendencia comparando el último año con el anterior. */
function YearTrend({ rows }: { rows: { anio: number; contratos: number; importe: number }[] }) {
  const maxC = Math.max(...rows.map((r) => r.contratos), 1);
  const last = rows[rows.length - 1];
  const prev = rows.length > 1 ? rows[rows.length - 2] : null;
  const delta = prev ? last.contratos - prev.contratos : 0;

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-sm font-semibold">Trayectoria por año</h3>
        {prev && (
          <Badge
            variant={delta > 0 ? "default" : delta < 0 ? "destructive" : "secondary"}
            className="gap-1"
          >
            {delta > 0 ? (
              <TrendingUp className="h-3 w-3" />
            ) : delta < 0 ? (
              <TrendingDown className="h-3 w-3" />
            ) : (
              <Minus className="h-3 w-3" />
            )}
            {delta > 0 ? `+${delta}` : delta} vs {prev.anio}
          </Badge>
        )}
      </div>
      <div className="space-y-1">
        {rows.map((r) => (
          <div key={r.anio} className="flex items-center gap-2 text-sm">
            <span className="w-12 shrink-0 tabular-nums text-muted-foreground">{r.anio}</span>
            <div className="h-4 flex-1 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary"
                style={{ width: `${(r.contratos / maxC) * 100}%` }}
              />
            </div>
            <span className="w-8 shrink-0 text-right tabular-nums text-xs">{r.contratos}</span>
            <span className="w-24 shrink-0 text-right font-mono text-xs text-muted-foreground">
              {formatCurrency(r.importe)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Cola de revisión de matches fuzzy                                  */
/* ------------------------------------------------------------------ */

function ReviewQueue() {
  const queryClient = useQueryClient();
  const { data } = useQuery<{ items: ReviewItem[] }>({
    queryKey: ["empresa-reviews"],
    queryFn: () => fetchWithAuth("/api/v1/empresas/reviews?limit=20"),
  });

  const resolve = useMutation({
    mutationFn: ({ id, accept }: { id: number; accept: boolean }) =>
      apiMutate("POST", `/api/v1/empresas/reviews/${id}`, { accept }),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["empresa-reviews"] });
      queryClient.invalidateQueries({ queryKey: ["empresas-stats"] });
      queryClient.invalidateQueries({ queryKey: ["empresas"] });
    },
  });

  const items = data?.items ?? [];
  if (items.length === 0) return null;

  return (
    <Card className="border-amber-500/40">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldQuestion className="h-4 w-4 text-amber-500" />
          Revisión de matches dudosos
        </CardTitle>
        <CardDescription>
          El resolutor no enlaza automáticamente nombres casi idénticos o NIFs en conflicto.
          ¿Es la misma empresa? <Check className="inline h-3 w-3" /> la une al candidato;{" "}
          <X className="inline h-3 w-3" /> crea una empresa nueva.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Visto en fuente</TableHead>
              <TableHead>Candidato existente</TableHead>
              <TableHead className="text-right">Similitud</TableHead>
              <TableHead className="w-28 text-right">Decisión</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="max-w-[260px]">
                  <span className="block truncate text-sm">{r.nombre_original}</span>
                  {r.nif && (
                    <span className="font-mono text-xs text-muted-foreground">{r.nif}</span>
                  )}
                </TableCell>
                <TableCell className="max-w-[260px]">
                  <span className="block truncate text-sm">{r.candidato_nombre ?? "—"}</span>
                  {r.candidato_nif && (
                    <span className="font-mono text-xs text-muted-foreground">
                      {r.candidato_nif}
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-right font-mono text-sm">
                  {(r.score * 100).toFixed(0)}%
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Misma empresa (unir al candidato)"
                      disabled={resolve.isPending}
                      onClick={() => resolve.mutate({ id: r.id, accept: true })}
                    >
                      <Check className="h-4 w-4 text-green-600" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Empresa distinta (crear nueva)"
                      disabled={resolve.isPending}
                      onClick={() => resolve.mutate({ id: r.id, accept: false })}
                    >
                      <X className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
