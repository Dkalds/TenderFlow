"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Download, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDebounce } from "@/hooks/use-debounce";
import { fetchWithAuth } from "@/lib/api-client";
import { descargarBlob } from "@/lib/export";
import { formatCurrency, formatDate, formatNumber, formatPercent, truncate } from "@/lib/utils";

import type { CompanyAward, CompanyAwardsData } from "./company-profile-types";

interface CompanyAwardsProps {
  empresaId: number;
  scopeQuery: string;
}

function csvCell(value: string | number | null | undefined): string {
  let text = value == null ? "" : String(value);
  if (/^[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

export function CompanyAwards({ empresaId, scopeQuery }: CompanyAwardsProps) {
  const [search, setSearch] = useState("");
  const [organ, setOrgan] = useState("");
  const [sort, setSort] = useState("fecha_desc");
  const [offset, setOffset] = useState(0);
  const [isExporting, setIsExporting] = useState(false);
  const debouncedSearch = useDebounce(search, 300);
  const debouncedOrgan = useDebounce(organ, 300);

  const params = useMemo(() => {
    const next = new URLSearchParams(scopeQuery);
    if (debouncedSearch) next.set("q", debouncedSearch);
    if (debouncedOrgan) next.set("organo", debouncedOrgan);
    next.set("sort", sort);
    next.set("limit", "25");
    next.set("offset", String(offset));
    return next.toString();
  }, [debouncedOrgan, debouncedSearch, offset, scopeQuery, sort]);

  const { data, isLoading } = useQuery<CompanyAwardsData>({
    queryKey: ["competitive-company-awards", empresaId, params],
    queryFn: () => fetchWithAuth(`/api/v1/competitive/empresas/${empresaId}/adjudicaciones?${params}`),
    placeholderData: keepPreviousData,
  });

  function updateSearch(value: string) {
    setSearch(value);
    setOffset(0);
  }

  function updateOrgan(value: string) {
    setOrgan(value);
    setOffset(0);
  }

  function updateSort(value: string) {
    setSort(value);
    setOffset(0);
  }

  async function exportAwards() {
    setIsExporting(true);
    try {
      const rows: CompanyAward[] = [];
      let pageOffset = 0;
      let total = 1;
      while (pageOffset < total) {
        const exportParams = new URLSearchParams(scopeQuery);
        if (debouncedSearch) exportParams.set("q", debouncedSearch);
        if (debouncedOrgan) exportParams.set("organo", debouncedOrgan);
        exportParams.set("sort", sort);
        exportParams.set("limit", "500");
        exportParams.set("offset", String(pageOffset));
        const page = await fetchWithAuth<CompanyAwardsData>(
          `/api/v1/competitive/empresas/${empresaId}/adjudicaciones?${exportParams.toString()}`,
        );
        rows.push(...page.items);
        total = page.total;
        pageOffset += page.items.length;
        if (!page.items.length) break;
      }

      const header = [
        "Fecha",
        "Licitación",
        "Órgano de contratación",
        "CPV",
        "CCAA",
        "Presupuesto",
        "Importe adjudicado",
        "Baja %",
        "Ofertas",
      ];
      const csv = [
        header.map(csvCell).join(","),
        ...rows.map((row) =>
          [
            row.fecha_adjudicacion,
            row.titulo ?? row.licitacion_id,
            row.organo_contratacion,
            row.cpv,
            row.ccaa,
            row.presupuesto_licitacion,
            row.importe_adjudicado,
            row.baja_pct,
            row.n_ofertas_recibidas,
          ]
            .map(csvCell)
            .join(","),
        ),
      ].join("\n");
      // `descargarBlob` en vez de un ancla propia: el fichero se compone en el
      // cliente y no pasa por `/exports/download`, que es el único sitio donde
      // se emitía el evento de exportación. `empresaId` no viaja a la métrica.
      descargarBlob(
        `adjudicaciones-empresa-${empresaId}.csv`,
        new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" }),
        "adjudicaciones-empresa",
      );
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <Card>
      <CardHeader className="gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <CardTitle>Histórico de adjudicaciones</CardTitle>
          <CardDescription>
            {formatNumber(data?.total ?? 0)} resultados · abre una fila para ver el expediente
          </CardDescription>
        </div>
        <Button variant="outline" className="min-h-10" onClick={exportAwards} disabled={isExporting || !data?.total}>
          <Download aria-hidden="true" />
          {isExporting ? "Preparando CSV…" : "Exportar CSV"}
        </Button>
      </CardHeader>
      <CardContent>
        <div className="mb-5 grid gap-3 lg:grid-cols-[1fr_1fr_220px]">
          <label className="relative" htmlFor="company-awards-search">
            <span className="sr-only">Buscar adjudicaciones</span>
            <Search
              className="text-muted-foreground pointer-events-none absolute top-3 left-3 h-4 w-4"
              aria-hidden="true"
            />
            <Input
              id="company-awards-search"
              className="min-h-10 pl-9"
              value={search}
              onChange={(event) => updateSearch(event.target.value)}
              placeholder="Título o identificador"
            />
          </label>
          <label htmlFor="company-awards-organ">
            <span className="sr-only">Filtrar por órgano</span>
            <Input
              id="company-awards-organ"
              className="min-h-10"
              value={organ}
              onChange={(event) => updateOrgan(event.target.value)}
              placeholder="Órgano de contratación"
            />
          </label>
          <Select value={sort} onValueChange={updateSort}>
            <SelectTrigger className="min-h-10" aria-label="Ordenar adjudicaciones">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="fecha_desc">Más recientes</SelectItem>
              <SelectItem value="fecha_asc">Más antiguas</SelectItem>
              <SelectItem value="importe_desc">Mayor importe</SelectItem>
              <SelectItem value="importe_asc">Menor importe</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Adjudicación</TableHead>
                <TableHead>Comprador</TableHead>
                <TableHead>Ámbito</TableHead>
                <TableHead className="text-right">Presupuesto</TableHead>
                <TableHead className="text-right">Adjudicado</TableHead>
                <TableHead className="text-right">Competencia</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                Array.from({ length: 5 }, (_, index) => (
                  <TableRow key={index}>
                    <TableCell colSpan={6}>
                      <Skeleton className="h-10 w-full" />
                    </TableCell>
                  </TableRow>
                ))
              ) : !data?.items.length ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-muted-foreground h-28 text-center">
                    No hay adjudicaciones que coincidan con estos filtros.
                  </TableCell>
                </TableRow>
              ) : (
                data.items.map((award) => (
                  <TableRow key={award.licitacion_id}>
                    <TableCell className="min-w-72">
                      <Link
                        href={`/detalle?lic=${encodeURIComponent(award.licitacion_id)}`}
                        className="hover:text-primary font-medium hover:underline"
                      >
                        {truncate(award.titulo ?? award.licitacion_id, 82)}
                      </Link>
                      <p className="text-muted-foreground mt-1 text-xs">{formatDate(award.fecha_adjudicacion)}</p>
                    </TableCell>
                    <TableCell className="max-w-64">
                      <span title={award.organo_contratacion ?? undefined}>
                        {truncate(award.organo_contratacion, 54) || "-"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {award.ccaa ? <Badge variant="outline">{award.ccaa}</Badge> : null}
                        {award.cpv ? <Badge variant="secondary">{award.cpv.slice(0, 2)}</Badge> : null}
                      </div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatCurrency(award.presupuesto_licitacion)}
                    </TableCell>
                    <TableCell className="text-right font-medium tabular-nums">
                      {formatCurrency(award.importe_adjudicado)}
                    </TableCell>
                    <TableCell className="text-right">
                      <p className="tabular-nums">{formatPercent(award.baja_pct)}</p>
                      <p className="text-muted-foreground text-xs">
                        {award.n_ofertas_recibidas == null ? "Ofertas: -" : `${award.n_ofertas_recibidas} ofertas`}
                      </p>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-muted-foreground text-xs">
            Mostrando {data?.total ? offset + 1 : 0}–{Math.min(offset + 25, data?.total ?? 0)} de{" "}
            {formatNumber(data?.total ?? 0)}
          </p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="min-h-9"
              disabled={!offset}
              onClick={() => setOffset(Math.max(0, offset - 25))}
            >
              <ArrowLeft aria-hidden="true" />
              Anterior
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="min-h-9"
              disabled={offset + 25 >= (data?.total ?? 0)}
              onClick={() => setOffset(offset + 25)}
            >
              Siguiente
              <ArrowRight aria-hidden="true" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
