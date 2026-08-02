"use client";

import { startTransition, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { KpiCard } from "@/components/charts/kpi-card";
import { ExportPopover } from "@/components/export-popover";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { EmptyState } from "@/components/ui/empty-state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { cn, formatNumber, formatCurrency, truncate } from "@/lib/utils";
import {
  Building2,
  Lock,
  Unlock,
  Network,
  Search,
  ArrowUpRight,
  ExternalLink,
} from "lucide-react";

const ForceGraph = dynamic(
  () => import("@/components/charts/force-graph").then((m) => ({ default: m.ForceGraph })),
  { ssr: false, loading: () => <Skeleton className="h-[440px] w-full rounded-md" /> },
);

/* ------------------------------------------------------------------ */
/*  Types — todo calculado en backend (ADR-014)                       */
/* ------------------------------------------------------------------ */

interface OrganoConcentracion {
  organo: string;
  n_empresas: number;
  n_contratos: number;
  importe_total: number;
  top_empresa: string;
  cuota_top1: number;
  cuota_top3: number;
  hhi: number;
  apertura: string;
}

interface ConcentracionResponse {
  organos: OrganoConcentracion[];
  total_organos: number;
}

interface GraphNode {
  name: string;
  type: "organo" | "empresa";
  degree: number;
  importe_total: number;
  key?: string | null;
}

interface GraphEdge {
  organo: string;
  empresa: string;
  contratos: number;
  importe_total: number;
  frecuencia_anual: number;
}

interface OrganCompanyGraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  total_organos: number;
  total_empresas: number;
}

interface EdgeLicitacion {
  licitacion_id: string | null;
  titulo: string | null;
  importe_adjudicado: number | null;
  fecha_adjudicacion: string | null;
  url: string | null;
}

interface EdgeDetailResponse {
  organo: string;
  empresa: string;
  n_licitaciones: number;
  importe_total: number;
  licitaciones: EdgeLicitacion[];
}

type Entity = { type: "organo" | "empresa"; key: string };

/* ------------------------------------------------------------------ */
/*  Apertura badge — semáforo de concentración                        */
/* ------------------------------------------------------------------ */

const APERTURA_STYLE: Record<string, string> = {
  Abierto: "border-success/25 bg-success/12 text-success",
  Moderado: "border-warning/30 bg-warning/15 text-warning",
  Cerrado: "border-destructive/25 bg-destructive/12 text-destructive",
};

function AperturaBadge({ value }: { value: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium",
        APERTURA_STYLE[value] ?? "border-muted-foreground/20 bg-muted-foreground/10 text-muted-foreground",
      )}
    >
      {value}
    </span>
  );
}

function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

/* ------------------------------------------------------------------ */
/*  Page                                                              */
/* ------------------------------------------------------------------ */

export default function RedOrganoEmpresaPage() {
  const router = useRouter();
  const [minContratos, setMinContratos] = useState(5);
  const [organoSearch, setOrganoSearch] = useState("");
  const [selected, setSelected] = useState<Entity | null>(null);
  const [edge, setEdge] = useState<{ organo: string; empresa: string } | null>(null);

  /* ── Hero: concentración por órgano ── */
  const { data, isLoading, error } = useFilteredQuery<ConcentracionResponse>(
    ["analytics", "organ-concentration", String(minContratos)],
    "/api/v1/analytics/organ-concentration",
    { staleTime: 5 * 60 * 1000 },
    { min_contratos: String(minContratos), top_n: "25" },
  );

  const organos = useMemo(() => data?.organos ?? [], [data]);
  const totalOrganos = data?.total_organos ?? 0;
  const nCerrados = organos.filter((o) => o.apertura === "Cerrado").length;
  const nAbiertos = organos.filter((o) => o.apertura === "Abierto").length;
  const hhiMediano = median(organos.map((o) => o.hhi));

  /* ── Ego-network de la entidad seleccionada ── */
  const { data: egoData, isLoading: egoLoading } = useFilteredQuery<OrganCompanyGraphResponse>(
    ["analytics", "organ-company-ego", selected?.type ?? "", selected?.key ?? ""],
    "/api/v1/analytics/organ-company-graph/ego",
    { enabled: !!selected, staleTime: 5 * 60 * 1000 },
    selected
      ? { entity_type: selected.type, entity_key: selected.key, top_neighbors: "30" }
      : undefined,
  );

  const { egoNodes, egoLinks, centerId } = useMemo(() => {
    const nodes = egoData?.nodes ?? [];
    const edges = egoData?.edges ?? [];
    const gNodes = nodes.map((n) => ({
      id: `${n.type}::${n.name}`,
      label: truncate(n.name, 26),
      group: n.type,
      size: Math.max(n.importe_total, 1),
      importe: n.importe_total,
      degree: n.degree,
    }));
    const gLinks = edges.map((e) => ({
      source: `organo::${e.organo}`,
      target: `empresa::${e.empresa}`,
      weight: e.contratos,
      importe: e.importe_total,
      contratos: e.contratos,
    }));
    return {
      egoNodes: gNodes,
      egoLinks: gLinks,
      centerId: selected ? `${selected.type}::${selected.key}` : undefined,
    };
  }, [egoData, selected]);

  /* ── Drill-down de arista ── */
  const { data: edgeData, isLoading: edgeLoading } = useFilteredQuery<EdgeDetailResponse>(
    ["analytics", "organ-company-edge", edge?.organo ?? "", edge?.empresa ?? ""],
    "/api/v1/analytics/organ-company-edge",
    { enabled: !!edge, staleTime: 5 * 60 * 1000 },
    edge ? { organo: edge.organo, empresa: edge.empresa } : undefined,
  );

  const parseId = (id: string): Entity => {
    const sep = id.indexOf("::");
    return { type: id.slice(0, sep) as "organo" | "empresa", key: id.slice(sep + 2) };
  };

  const handleNodeClick = (id: string) => {
    const { type, key } = parseId(id);
    // Click en el nodo central → ficha; en un vecino → re-centra el ego en él.
    if (selected && type === selected.type && key === selected.key) {
      router.push(
        type === "organo"
          ? `/organos?q=${encodeURIComponent(key)}`
          : `/empresas?q=${encodeURIComponent(key)}`,
      );
    } else {
      setSelected({ type, key });
    }
  };

  const handleLinkClick = (source: string, target: string) => {
    setEdge({ organo: parseId(source).key, empresa: parseId(target).key });
  };

  const selectOrgano = (organo: string) => {
    if (organo) setSelected({ type: "organo", key: organo });
  };

  if (error) {
    return (
      <div
        className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center"
        role="alert"
      >
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center">
        <div className="flex-1" />
        <ExportPopover
          endpoint="/api/v1/exports/download"
          extraParams={{ seccion: "red-organo-empresa" }}
          className="[&>button]:h-8 [&>button]:px-2.5 [&>button]:py-0 [&>button]:text-xs"
        />
      </div>

      {/* KPI Row — lectura de concentración */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Órganos analizados"
          value={isLoading ? undefined : formatNumber(totalOrganos)}
          icon={Building2}
          loading={isLoading}
        />
        <KpiCard
          title="Cotos cerrados"
          value={isLoading ? undefined : formatNumber(nCerrados)}
          subtitle="HHI ≥ 2500 (top ranking)"
          icon={Lock}
          loading={isLoading}
        />
        <KpiCard
          title="Compradores abiertos"
          value={isLoading ? undefined : formatNumber(nAbiertos)}
          subtitle="HHI < 1500 (top ranking)"
          icon={Unlock}
          loading={isLoading}
        />
        <KpiCard
          title="HHI mediano"
          value={isLoading ? undefined : formatNumber(Math.round(hhiMediano))}
          subtitle="0 = competitivo · 10000 = monopolio"
          icon={Network}
          loading={isLoading}
        />
      </div>

      {/* Ranking y grafo lado a lado. Ambas pantallas ya evitaban abrir con la
          maraña, pero el grafo estaba debajo: al re-centrar en un vecino
          perdías de vista la fila de la que venías. Ahora eliges un órgano y su
          vecindario aparece a la derecha sin que la tabla se mueva. */}
      <div className="grid items-start gap-4 xl:grid-cols-2">
      {/* HERO: leaderboard de concentración / incumbencia */}
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle className="text-base flex items-center gap-2">
                <Lock className="h-4 w-4" />
                Concentración por órgano
              </CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                Ordenado de más cerrado a más abierto. Elegí un órgano para ver su red.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Mín. adjudicaciones</span>
              <input
                type="range"
                aria-label="Mínimo de adjudicaciones por órgano"
                min={1}
                max={30}
                step={1}
                value={minContratos}
                onChange={(e) => setMinContratos(Number(e.target.value))}
                className="w-24 accent-primary"
              />
              <Badge variant="secondary" className="text-xs">
                {minContratos}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-11 w-full" />
              ))}
            </div>
          ) : organos.length > 0 ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="text-left text-muted-foreground">
                    <TableHead>Órgano</TableHead>
                    <TableHead>Apertura</TableHead>
                    <TableHead>Incumbente (top-1)</TableHead>
                    <TableHead className="text-right">Cuota top-1</TableHead>
                    <TableHead className="text-right">CR3</TableHead>
                    <TableHead className="text-right">Empresas</TableHead>
                    <TableHead className="text-right">Importe</TableHead>
                    <TableHead className="text-right">HHI</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {organos.map((o) => {
                    const isSel = selected?.type === "organo" && selected.key === o.organo;
                    return (
                      <TableRow
                        key={o.organo}
                        onClick={() => selectOrgano(o.organo)}
                        className={cn(
                          "cursor-pointer transition-colors",
                          isSel ? "bg-primary/5" : "hover:bg-muted/50",
                        )}
                      >
                        <TableCell className="font-medium">{truncate(o.organo, 42)}</TableCell>
                        <TableCell>
                          <AperturaBadge value={o.apertura} />
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {truncate(o.top_empresa, 30)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {o.cuota_top1.toFixed(1)}%
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-muted-foreground">
                          {o.cuota_top3.toFixed(1)}%
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatNumber(o.n_empresas)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-muted-foreground">
                          {formatCurrency(o.importe_total)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums font-medium">
                          {formatNumber(Math.round(o.hhi))}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              <Separator className="my-3" />
              <p className="text-xs text-muted-foreground">
                {organos.length} de {formatNumber(totalOrganos)} órganos (top por
                concentración). HHI = índice Herfindahl-Hirschman sobre el importe
                por empresa.
              </p>
            </div>
          ) : (
            <EmptyState
              icon={Lock}
              title="Sin datos de concentración"
              hint="Ningún órgano supera el mínimo de adjudicaciones para los filtros actuales."
            />
          )}
        </CardContent>
      </Card>

      {/* Ego-network de la entidad seleccionada */}
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <CardTitle className="text-base flex items-center gap-2">
                <Network className="h-4 w-4" />
                Red de la entidad
                {selected && (
                  <span className="font-normal text-muted-foreground">
                    · {truncate(selected.key, 40)}
                  </span>
                )}
              </CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                {selected
                  ? "Click en un vecino para re-centrar; en una arista para ver las licitaciones."
                  : "Elegí un órgano del ranking o buscá uno para ver su vecindario."}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <SearchAutocomplete
                className="w-64"
                placeholder="Buscar órgano…"
                value={organoSearch}
                onChange={setOrganoSearch}
                onSubmit={selectOrgano}
                suggestions={organos.map((o) => o.organo)}
                leftIcon={<Search className="h-4 w-4" />}
                inputClassName="pl-9"
                aria-label="Buscar órgano para explorar su red"
              />
              {selected && (
                <Link
                  href={
                    selected.type === "organo"
                      ? `/organos?q=${encodeURIComponent(selected.key)}`
                      : `/empresas?q=${encodeURIComponent(selected.key)}`
                  }
                  className="inline-flex items-center gap-1 whitespace-nowrap rounded border px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted"
                >
                  Ver ficha <ArrowUpRight className="h-3.5 w-3.5" />
                </Link>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {!selected ? (
            <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-muted py-16 text-center">
              <Network className="mb-4 h-14 w-14 text-muted-foreground/30" />
              <p className="text-muted-foreground">
                Ninguna entidad seleccionada. Hacé click en un órgano del ranking.
              </p>
            </div>
          ) : egoLoading ? (
            <Skeleton className="h-[440px] w-full" />
          ) : egoNodes.length > 0 ? (
            <ForceGraph
              nodes={egoNodes}
              links={egoLinks}
              height={440}
              layout="ego"
              centerId={centerId}
              groupLabels={{ organo: "Órgano", empresa: "Empresa" }}
              onNodeClick={handleNodeClick}
              onLinkClick={handleLinkClick}
            />
          ) : (
            <EmptyState
              icon={Network}
              title="Sin relaciones"
              hint="Esta entidad no tiene adjudicaciones para los filtros actuales."
            />
          )}
        </CardContent>
      </Card>
      </div>

      {/* Drill-down de arista: licitaciones que sustentan la relación */}
      {/* startTransition: cerrar diferido evita bloquear el hilo principal en
          el propio clic del overlay (INP). */}
      <Sheet open={!!edge} onOpenChange={(o) => !o && startTransition(() => setEdge(null))}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
          <SheetHeader>
            <SheetTitle>Licitaciones de la relación</SheetTitle>
            <SheetDescription>
              {edge ? `${truncate(edge.organo, 40)} → ${truncate(edge.empresa, 40)}` : ""}
            </SheetDescription>
          </SheetHeader>
          <div className="mt-4">
            {edgeLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : edgeData && edgeData.licitaciones.length > 0 ? (
              <>
                <div className="mb-3 flex items-center gap-4 text-sm">
                  <span className="text-muted-foreground">
                    {formatNumber(edgeData.n_licitaciones)} licitaciones
                  </span>
                  <span className="font-medium tabular-nums">
                    {formatCurrency(edgeData.importe_total)}
                  </span>
                </div>
                <ul className="space-y-2">
                  {edgeData.licitaciones.map((lic, i) => (
                    <li
                      key={`${lic.licitacion_id ?? "sin-id"}-${i}`}
                      className="rounded-md border border-border p-3"
                    >
                      <div className="flex items-start justify-between gap-2">
                        {lic.licitacion_id ? (
                          <Link
                            href={`/detalle?lic=${encodeURIComponent(lic.licitacion_id)}`}
                            className="text-sm font-medium hover:text-primary"
                          >
                            {truncate(lic.titulo ?? lic.licitacion_id, 70)}
                          </Link>
                        ) : (
                          <span className="text-sm font-medium">
                            {truncate(lic.titulo ?? "Sin título", 70)}
                          </span>
                        )}
                        {lic.url && (
                          <a
                            href={lic.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="mt-0.5 shrink-0 text-muted-foreground hover:text-primary"
                            aria-label="Abrir licitación en origen"
                          >
                            <ExternalLink className="h-3.5 w-3.5" />
                          </a>
                        )}
                      </div>
                      <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                        {lic.importe_adjudicado != null && (
                          <span className="tabular-nums">
                            {formatCurrency(lic.importe_adjudicado)}
                          </span>
                        )}
                        {lic.fecha_adjudicacion && <span>{lic.fecha_adjudicacion}</span>}
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="py-8 text-center text-sm text-muted-foreground">
                Sin licitaciones para esta relación.
              </p>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
