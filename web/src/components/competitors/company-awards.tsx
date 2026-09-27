"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Download, Search } from "lucide-react";

import { Panel, PanelError, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Pista } from "@/components/ui/pista";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDebounce } from "@/hooks/use-debounce";
import { fetchWithAuth } from "@/lib/api-client";
import { descargarBlob } from "@/lib/export";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { EMPTY, formatCurrency, formatDate, formatNumber, formatPercent, truncate } from "@/lib/utils";

import type { CompanyAward, CompanyAwardsData } from "./company-profile-types";
import { competitiveKeys } from "@/lib/query-keys";

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

  const { data, isLoading, error, refetch } = useQuery<CompanyAwardsData>({
    queryKey: competitiveKeys.companyAwards(empresaId, params),
    queryFn: () => fetchWithAuth(`/api/v1/competitive/empresas/${empresaId}/adjudicaciones?${params}`),
    placeholderData: keepPreviousData,
    // El fallo se dice en la tabla (PanelError), no como «no hay adjudicaciones».
    meta: META_ERROR_EN_LINEA,
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
    <Panel>
      <PanelTitle
        title="Histórico de adjudicaciones"
        hint={`${formatNumber(data?.total ?? 0)} resultados`}
        actions={
          <Button variant="outline" size="sm" onClick={exportAwards} disabled={isExporting || !data?.total}>
            <Download aria-hidden="true" />
            {isExporting ? "Preparando CSV…" : "Exportar CSV"}
          </Button>
        }
      />
        <div className="mb-4 grid gap-3 lg:grid-cols-[1fr_1fr_220px]">
          <label className="relative" htmlFor="company-awards-search">
            <span className="sr-only">Buscar adjudicaciones</span>
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              id="company-awards-search"
              className="pl-8"
              value={search}
              onChange={(event) => updateSearch(event.target.value)}
              placeholder="Título o identificador"
            />
          </label>
          <label htmlFor="company-awards-organ">
            <span className="sr-only">Filtrar por órgano</span>
            <Input
              id="company-awards-organ"
              value={organ}
              onChange={(event) => updateOrgan(event.target.value)}
              placeholder="Órgano de contratación"
            />
          </label>
          <Select value={sort} onValueChange={updateSort}>
            <SelectTrigger aria-label="Ordenar adjudicaciones">
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

        {error ? (
          <PanelError
            title="No se pudieron cargar las adjudicaciones"
            error={error}
            onRetry={() => void refetch()}
            height={200}
          />
        ) : (
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
                      <Skeleton className="h-9 w-full" />
                    </TableCell>
                  </TableRow>
                ))
              ) : !data?.items.length ? (
                <TableRow>
                  <TableCell colSpan={6} className="h-28 text-center text-muted-foreground">
                    No hay adjudicaciones que coincidan con estos filtros.
                  </TableCell>
                </TableRow>
              ) : (
                data.items.map((award) => (
                  <TableRow key={award.licitacion_id}>
                    <TableCell className="min-w-72">
                      <Link
                        href={`/detalle?lic=${encodeURIComponent(award.licitacion_id)}`}
                        className="font-medium transition-colors hover:text-primary"
                      >
                        {truncate(award.titulo ?? award.licitacion_id, 82)}
                      </Link>
                      <p className="mt-1 text-tf-meta text-muted-foreground">{formatDate(award.fecha_adjudicacion)}</p>
                    </TableCell>
                    <TableCell className="max-w-64">
                      {/* Entero en el DOM y recortado por CSS: el lector lo lee
                          completo y la `Pista` lo enseña al puntero sin sumar
                          una parada de tabulación por fila. */}
                      <Pista contenido={award.organo_contratacion}>
                        <span className="block truncate">{award.organo_contratacion || EMPTY}</span>
                      </Pista>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {award.ccaa ? (
                          <Badge variant="outline" size="sm">
                            {award.ccaa}
                          </Badge>
                        ) : null}
                        {award.cpv ? (
                          <Badge variant="secondary" size="sm" className="font-mono">
                            {award.cpv.slice(0, 2)}
                          </Badge>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell numeric>{formatCurrency(award.presupuesto_licitacion)}</TableCell>
                    <TableCell numeric className="font-medium">
                      {formatCurrency(award.importe_adjudicado)}
                    </TableCell>
                    <TableCell numeric>
                      <p>{formatPercent(award.baja_pct)}</p>
                      <p className="text-tf-meta text-muted-foreground">
                        {award.n_ofertas_recibidas == null ? `Ofertas: ${EMPTY}` : `${award.n_ofertas_recibidas} ofertas`}
                      </p>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-tf-meta text-muted-foreground">
            Mostrando {data?.total ? offset + 1 : 0}–{Math.min(offset + 25, data?.total ?? 0)} de{" "}
            {formatNumber(data?.total ?? 0)}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 25))}>
              Anterior
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={offset + 25 >= (data?.total ?? 0)}
              onClick={() => setOffset(offset + 25)}
            >
              Siguiente
            </Button>
          </div>
        </div>
    </Panel>
  );
}
