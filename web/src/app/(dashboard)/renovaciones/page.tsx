"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { CHART_SERIES } from "@/lib/chart-colors";
import { formatCurrency, formatNumber, truncate } from "@/lib/utils";
import { CalendarClock, Euro, Building2, Timer, ExternalLink, Search } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface Renovacion {
  licitacion_id: string;
  titulo: string | null;
  organo_contratacion: string | null;
  cpv: string | null;
  ccaa: string | null;
  url: string | null;
  empresa_id: number | null;
  empresa: string | null;
  es_ute: number | null;
  importe_adjudicado: number | null;
  fecha_adjudicacion: string | null;
  fecha_fin_efectiva: string | null;
  dias_restantes: number | null;
}

interface ResumenEmpresa {
  empresa_id: number | null;
  empresa: string | null;
  contratos_venciendo: number;
  importe_en_juego: number;
  proximo_vencimiento: string | null;
}

const HORIZONTES = [
  { value: "3", label: "3 meses" },
  { value: "6", label: "6 meses" },
  { value: "12", label: "12 meses" },
  { value: "24", label: "24 meses" },
];

function diasBadgeVariant(dias: number | null): "destructive" | "secondary" | "outline" {
  if (dias == null) return "outline";
  if (dias <= 30) return "destructive";
  if (dias <= 90) return "secondary";
  return "outline";
}

export default function RenovacionesPage() {
  const [meses, setMeses] = useState("6");
  const [empresaSearch, setEmpresaSearch] = useState("");

  const { data, isLoading, error } = useQuery<{ items: Renovacion[] }>({
    queryKey: ["renovaciones", meses],
    queryFn: () =>
      fetchWithAuth(`/api/v1/competitive/renovaciones?months=${meses}&limit=1000`),
    staleTime: 5 * 60 * 1000,
  });

  const { data: resumen } = useQuery<{ items: ResumenEmpresa[] }>({
    queryKey: ["renovaciones-resumen", meses],
    queryFn: () =>
      fetchWithAuth(`/api/v1/competitive/renovaciones/resumen?months=${meses}`),
    staleTime: 5 * 60 * 1000,
  });

  const items = useMemo(() => {
    const all = data?.items ?? [];
    if (!empresaSearch) return all;
    const q = empresaSearch.toLowerCase();
    return all.filter(
      (r) =>
        (r.empresa ?? "").toLowerCase().includes(q) ||
        (r.organo_contratacion ?? "").toLowerCase().includes(q) ||
        (r.titulo ?? "").toLowerCase().includes(q),
    );
  }, [data, empresaSearch]);

  const kpis = useMemo(() => {
    const all = data?.items ?? [];
    const importe = all.reduce((acc, r) => acc + (r.importe_adjudicado ?? 0), 0);
    const en30 = all.filter((r) => (r.dias_restantes ?? 9999) <= 30).length;
    const empresas = new Set(all.map((r) => r.empresa_id ?? r.empresa)).size;
    return { contratos: all.length, importe, en30, empresas };
  }, [data]);

  const topCartera = useMemo(
    () =>
      (resumen?.items ?? [])
        .slice(0, 10)
        .map((r) => ({
          empresa: truncate(r.empresa ?? "—", 28),
          importe: r.importe_en_juego,
          contratos: r.contratos_venciendo,
        })),
    [resumen],
  );

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
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Renovaciones</h1>
          <p className="text-muted-foreground">
            Contratos adjudicados que vencen pronto: o los defiende el adjudicatario actual o
            se los disputa quien llegue primero.
          </p>
        </div>
        <Select value={meses} onValueChange={setMeses}>
          <SelectTrigger className="w-[140px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {HORIZONTES.map((h) => (
              <SelectItem key={h.value} value={h.value}>
                {h.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* KPIs */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Contratos venciendo"
          value={isLoading ? "…" : formatNumber(kpis.contratos)}
          icon={CalendarClock}
        />
        <KpiCard
          title="Importe en juego"
          value={isLoading ? "…" : formatCurrency(kpis.importe)}
          icon={Euro}
        />
        <KpiCard
          title="Vencen en 30 días"
          value={isLoading ? "…" : formatNumber(kpis.en30)}
          icon={Timer}
        />
        <KpiCard
          title="Empresas afectadas"
          value={isLoading ? "…" : formatNumber(kpis.empresas)}
          icon={Building2}
        />
      </div>

      {/* Cartera en juego por empresa */}
      <Card>
        <CardHeader>
          <CardTitle>Cartera en juego por empresa</CardTitle>
          <CardDescription>
            Top 10 adjudicatarios por importe de contratos que vencen en {meses} meses.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[320px] w-full" />
          ) : topCartera.length === 0 ? (
            <EmptyState
              icon={CalendarClock}
              title="Sin vencimientos en la ventana"
              hint="Amplía el horizonte temporal para ver más contratos."
            />
          ) : (
            <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={topCartera} layout="vertical" margin={{ left: 120 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis
                    type="number"
                    tickFormatter={(v: number) => formatCurrency(v)}
                    fontSize={11}
                  />
                  <YAxis type="category" dataKey="empresa" width={120} fontSize={11} />
                  <Tooltip
                    formatter={(value) => [formatCurrency(Number(value ?? 0)), "Importe en juego"]}
                  />
                  <Bar dataKey="importe" fill={CHART_SERIES[0]} radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartErrorBoundary>
          )}
        </CardContent>
      </Card>

      {/* Tabla detalle */}
      <Card>
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>Contratos que vencen</CardTitle>
            <CardDescription>
              {formatNumber(items.length)} contratos ordenados por proximidad del vencimiento.
            </CardDescription>
          </div>
          <div className="relative w-full sm:w-72">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Filtrar por empresa, órgano o título…"
              value={empresaSearch}
              onChange={(e) => setEmpresaSearch(e.target.value)}
              className="pl-8"
            />
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[400px] w-full" />
          ) : items.length === 0 ? (
            <EmptyState
              icon={Search}
              title="Sin resultados"
              hint="Ningún contrato coincide con el filtro actual."
            />
          ) : (
            <div className="max-h-[560px] overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Vence</TableHead>
                    <TableHead>Contrato</TableHead>
                    <TableHead>Adjudicatario</TableHead>
                    <TableHead>Órgano</TableHead>
                    <TableHead className="text-right">Importe</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((r) => (
                    <TableRow key={`${r.licitacion_id}-${r.empresa_id ?? r.empresa}`}>
                      <TableCell className="whitespace-nowrap">
                        <div className="flex flex-col gap-1">
                          <span className="text-sm">{r.fecha_fin_efectiva ?? "—"}</span>
                          <Badge variant={diasBadgeVariant(r.dias_restantes)} className="w-fit">
                            {r.dias_restantes != null ? `${r.dias_restantes} días` : "—"}
                          </Badge>
                        </div>
                      </TableCell>
                      <TableCell className="max-w-[320px]">
                        <div className="flex items-start gap-1.5">
                          <span className="text-sm leading-snug">
                            {truncate(r.titulo ?? r.licitacion_id, 90)}
                          </span>
                          {r.url && (
                            <a
                              href={r.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground"
                              aria-label="Abrir anuncio original"
                            >
                              <ExternalLink className="h-3.5 w-3.5" />
                            </a>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="max-w-[220px]">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate text-sm">{r.empresa ?? "—"}</span>
                          {r.es_ute ? <Badge variant="outline">UTE</Badge> : null}
                        </div>
                      </TableCell>
                      <TableCell className="max-w-[220px] truncate text-sm text-muted-foreground">
                        {r.organo_contratacion ?? "—"}
                      </TableCell>
                      <TableCell className="text-right text-sm font-medium whitespace-nowrap">
                        {r.importe_adjudicado != null
                          ? formatCurrency(r.importe_adjudicado)
                          : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
