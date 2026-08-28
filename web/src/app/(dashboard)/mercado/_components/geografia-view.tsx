"use client";

/**
 * Vista compartida por la ruta `/geografia` y por `?vista=geografia` del espacio
 * Mercado. Ver la nota en `tendencias-view.tsx` sobre por qué el cuerpo no vive
 * en el `page.tsx` de la ruta.
 */

import { EmptyState } from "@/components/ui/empty-state";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters } from "@/lib/filters";
import { toggleValue } from "@/lib/chart-interaction";
import { KpiCard, KpiStrip } from "@/components/charts/kpi-card";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { ExportPopover } from "@/components/export-popover";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
const SpainMap = dynamic(() => import("@/components/charts/spain-map").then(m => ({ default: m.SpainMap })), { ssr: false, loading: () => <Skeleton className="h-[420px] w-full rounded-md" /> });
const GeografiaBarChart = dynamic(() => import("@/components/charts/geografia-charts").then(m => ({ default: m.GeografiaBarChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });
const GeografiaPieChart = dynamic(() => import("@/components/charts/geografia-charts").then(m => ({ default: m.GeografiaPieChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { MapPin, Hash, Trophy, ArrowUpDown, ArrowUp, ArrowDown, DollarSign, Map } from "lucide-react";

interface GeoItem {
  ccaa: string;
  count: number;
  importe: number;
  pct: number;
}

interface ProvinciaItem {
  provincia: string;
  count: number;
  importe: number;
}

interface GeographyResponse {
  by_ccaa: GeoItem[];
  by_provincia?: ProvinciaItem[];
}


type SortKey = "ccaa" | "count" | "importe" | "pct";
type SortDir = "asc" | "desc";
type ProvSortKey = "provincia" | "count" | "importe";

export default function GeografiaView() {
  const [sortKey, setSortKey] = useState<SortKey>("count");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [provSortKey, setProvSortKey] = useState<ProvSortKey>("count");
  const [provSortDir, setProvSortDir] = useState<SortDir>("desc");
  const [mapMetric, setMapMetric] = useState<"count" | "importe">("count");

  const { ccaas, setCcaas } = useFilters();
  const activeCcaa = useMemo(() => new Set(ccaas), [ccaas]);
  const toggleCcaa = (ccaa: string) => setCcaas(toggleValue(ccaa, ccaas));

  const { data, isLoading, error } = useFilteredQuery<GeographyResponse>(
    ["analytics", "geography"],
    "/api/v1/analytics/geography",
    { staleTime: 5 * 60 * 1000 },
  );

  const items = useMemo(() => data?.by_ccaa ?? [], [data]);

  const topCcaa = items.length > 0 ? items[0].ccaa : "-";
  const top3Concentration = useMemo(() => {
    if (items.length === 0) return 0;
    const total = items.reduce((s, i) => s + i.count, 0);
    const top3 = items.slice(0, 3).reduce((s, i) => s + i.count, 0);
    return total > 0 ? (top3 / total) * 100 : 0;
  }, [items]);

  // CCAA with highest average ticket
  const ccaaMayorTicket = useMemo(() => {
    if (items.length === 0) return "-";
    let best = items[0];
    let bestRatio = best.count > 0 ? best.importe / best.count : 0;
    for (const item of items) {
      if (item.count === 0) continue;
      const ratio = item.importe / item.count;
      if (ratio > bestRatio) {
        best = item;
        bestRatio = ratio;
      }
    }
    return best.ccaa;
  }, [items]);

  const mapData = useMemo(
    () => items.map((i) => ({ ccaa: i.ccaa, value: i[mapMetric] })),
    [items, mapMetric],
  );

  const barData = useMemo(
    () => [...items].sort((a, b) => b.count - a.count),
    [items],
  );

  const pieData = useMemo(() => {
    const sorted = [...items].sort((a, b) => b.importe - a.importe);
    if (sorted.length <= 10) return sorted;
    const top = sorted.slice(0, 9);
    const rest = sorted.slice(9);
    const otherImporte = rest.reduce((s, i) => s + i.importe, 0);
    return [
      ...top,
      { ccaa: "Otros", count: 0, importe: otherImporte, pct: 0 },
    ];
  }, [items]);

  const sortedItems = useMemo(() => {
    const sorted = [...items];
    sorted.sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      if (typeof aVal === "string" && typeof bVal === "string") {
        return sortDir === "asc"
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      }
      return sortDir === "asc"
        ? (aVal as number) - (bVal as number)
        : (bVal as number) - (aVal as number);
    });
    return sorted;
  }, [items, sortKey, sortDir]);

  // Provincias agregadas en backend sobre el dataset completo y respetando los
  // filtros globales (vía useFilteredQuery), no un sample cliente de limit=500.
  const provinciaData = useMemo(() => data?.by_provincia ?? [], [data]);

  const sortedProvincias = useMemo(() => {
    const sorted = [...provinciaData];
    sorted.sort((a, b) => {
      if (provSortKey === "provincia") {
        return provSortDir === "asc"
          ? a.provincia.localeCompare(b.provincia)
          : b.provincia.localeCompare(a.provincia);
      }
      const aVal = a[provSortKey] as number;
      const bVal = b[provSortKey] as number;
      return provSortDir === "asc" ? aVal - bVal : bVal - aVal;
    });
    return sorted;
  }, [provinciaData, provSortKey, provSortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  function toggleProvSort(key: ProvSortKey) {
    if (provSortKey === key) {
      setProvSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setProvSortKey(key);
      setProvSortDir("desc");
    }
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="sr-only">Geografía</h1>
          <p className="text-muted-foreground">
            Distribución geográfica por Comunidad Autónoma.
          </p>
        </div>
        <ExportPopover
          endpoint="/api/v1/exports/download"
          extraParams={{ section: "geografia" }}
        />
      </div>

      {/* KPI Row */}
      <KpiStrip columns={4}>
        <KpiCard
          title="CCAA Más Activa"
          value={isLoading ? undefined : topCcaa}
          icon={Trophy}
          loading={isLoading}
        />
        <KpiCard
          title="Concentración Top 3"
          value={isLoading ? undefined : formatPercent(top3Concentration)}
          subtitle="del total"
          icon={MapPin}
          loading={isLoading}
        />
        <KpiCard
          title="Total CCAAs"
          value={isLoading ? undefined : formatNumber(items.length)}
          icon={Hash}
          loading={isLoading}
        />
        <KpiCard
          title="Mayor Ticket Medio"
          value={isLoading ? undefined : ccaaMayorTicket}
          subtitle="CCAA con mayor importe/licitación"
          icon={DollarSign}
          loading={isLoading}
        />
      </KpiStrip>

      {/* Choropleth Map */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <Map className="h-4 w-4" />
              Mapa por {mapMetric === "count" ? "Licitaciones" : "Importe"}
            </CardTitle>
          <div className="flex items-center gap-1 rounded-lg border p-0.5">
              <Button
                size="sm"
                variant={mapMetric === "count" ? "default" : "ghost"}
                className="h-7 px-3 text-xs"
                onClick={() => setMapMetric("count")}
              >
                Licitaciones
              </Button>
              <Button
                size="sm"
                variant={mapMetric === "importe" ? "default" : "ghost"}
                className="h-7 px-3 text-xs"
                onClick={() => setMapMetric("importe")}
              >
                Importe €
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[500px] w-full" />
          ) : (
            <SpainMap
              data={mapData}
              metric={mapMetric === "count" ? "Licitaciones" : "Importe €"}
              height={480}
              onCcaaClick={toggleCcaa}
            />
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Horizontal Bar Chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">CCAAs por Cantidad</CardTitle>
            <CardDescription>Clic en una CCAA para filtrar</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : barData.length > 0 ? (
              <GeografiaBarChart data={barData} onSelect={toggleCcaa} />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        {/* Pie Chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Distribución por Importe
            </CardTitle>
            <CardDescription>Clic en una CCAA para filtrar</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : pieData.length > 0 ? (
              <GeografiaPieChart data={pieData} onSelect={toggleCcaa} />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>

      {/* CCAA Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Todas las CCAAs</CardTitle>
          <CardDescription>Clic en una CCAA para filtrar</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table className="w-full text-sm">
                <TableHeader>
                  <TableRow className="border-b text-left">
                    {(
                      [
                        ["ccaa", "CCAA"],
                        ["count", "Cantidad"],
                        ["importe", "Importe"],
                        ["pct", "%"],
                      ] as [SortKey, string][]
                    ).map(([key, label]) => (
                      <TableHead
                        key={key}
                        className={`pb-2 pr-4 font-medium text-muted-foreground ${key !== "ccaa" ? "text-right" : ""}`}
                      >
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-auto p-0 font-medium text-muted-foreground hover:text-foreground"
                          onClick={() => toggleSort(key)}
                        >
                          {label}
                          {sortKey === key ? (
                            sortDir === "asc" ? (
                              <ArrowUp className="ml-1 h-3 w-3 text-primary" />
                            ) : (
                              <ArrowDown className="ml-1 h-3 w-3 text-primary" />
                            )
                          ) : (
                            <ArrowUpDown className="ml-1 h-3 w-3 opacity-40" />
                          )}
                        </Button>
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedItems.map((item, idx) => {
                    const isActive = activeCcaa.has(item.ccaa);
                    return (
                    <TableRow
                      key={idx}
                      onClick={() => toggleCcaa(item.ccaa)}
                      className={`cursor-pointer border-b border-border/50 hover:bg-muted/50 ${isActive ? "bg-primary/10" : ""}`}
                    >
                      {/* El conmutador es un botón real dentro de la celda, no
                          la fila. `aria-pressed` sobre un `<tr>` no lo lee
                          nadie —`row` no admite ese estado— y la fila entera no
                          era alcanzable por teclado: quien no usa ratón no
                          tenía forma de filtrar por CCAA desde esta tabla.
                          El `onClick` del `<tr>` sobrevive como atajo. */}
                      <TableCell className="py-2 pr-4 font-medium">
                        <button
                          type="button"
                          aria-pressed={isActive}
                          className="cursor-pointer text-left font-medium"
                          onClick={(e) => {
                            // Si no se corta, el clic sube al `<tr>` y el toggle
                            // se aplica dos veces (vuelve al estado inicial).
                            e.stopPropagation();
                            toggleCcaa(item.ccaa);
                          }}
                        >
                          {item.ccaa}
                        </button>
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatNumber(item.count)}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatCurrency(item.importe)}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatPercent(item.pct)}
                      </TableCell>
                    </TableRow>
                    );
                  })}
                  {sortedItems.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={4}
                        className="py-8 text-center text-muted-foreground"
                      >
                        Sin resultados
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Provinces Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Provincias</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : sortedProvincias.length > 0 ? (
            <div className="overflow-x-auto">
              <Table className="w-full text-sm">
                <TableHeader>
                  <TableRow className="border-b text-left">
                    {(
                      [
                        ["provincia", "Provincia"],
                        ["count", "Cantidad"],
                        ["importe", "Importe"],
                      ] as [ProvSortKey, string][]
                    ).map(([key, label]) => (
                      <TableHead
                        key={key}
                        className={`pb-2 pr-4 font-medium text-muted-foreground ${key !== "provincia" ? "text-right" : ""}`}
                      >
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-auto p-0 font-medium text-muted-foreground hover:text-foreground"
                          onClick={() => toggleProvSort(key)}
                        >
                          {label}
                          {provSortKey === key ? (
                            provSortDir === "asc" ? (
                              <ArrowUp className="ml-1 h-3 w-3 text-primary" />
                            ) : (
                              <ArrowDown className="ml-1 h-3 w-3 text-primary" />
                            )
                          ) : (
                            <ArrowUpDown className="ml-1 h-3 w-3 opacity-40" />
                          )}
                        </Button>
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedProvincias.map((item, idx) => (
                    <TableRow
                      key={idx}
                      className="border-b border-border/50 hover:bg-muted/50"
                    >
                      <TableCell className="py-2 pr-4 font-medium">
                        {item.provincia}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatNumber(item.count)}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatCurrency(item.importe)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <p className="py-8 text-center text-muted-foreground">
              Sin datos de provincia
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
