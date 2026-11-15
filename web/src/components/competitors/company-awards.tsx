"use client";

import { useMemo, useState } from "react";
import { EnlaceFicha } from "@/components/ficha/enlace-ficha";
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
import { todasLasAdjudicaciones, useAdjudicacionesEmpresa } from "@/hooks/use-empresa-competencia";
import { csvBlob, descargarBlob } from "@/lib/export";
import { EMPTY, formatCurrency, formatDate, formatNumber, formatPercent, truncate } from "@/lib/utils";

interface CompanyAwardsProps {
  empresaId: number;
  scopeQuery: string;
}

export function CompanyAwards({ empresaId, scopeQuery }: CompanyAwardsProps) {
  const [search, setSearch] = useState("");
  const [organ, setOrgan] = useState("");
  const [sort, setSort] = useState("fecha_desc");
  const [offset, setOffset] = useState(0);
  const [isExporting, setIsExporting] = useState(false);
  const debouncedSearch = useDebounce(search, 300);
  const debouncedOrgan = useDebounce(organ, 300);

  // Filtros y orden, sin la página: lo que comparten la tabla y la exportación.
  const filtros = useMemo(() => {
    const next = new URLSearchParams(scopeQuery);
    if (debouncedSearch) next.set("q", debouncedSearch);
    if (debouncedOrgan) next.set("organo", debouncedOrgan);
    next.set("sort", sort);
    return next.toString();
  }, [debouncedOrgan, debouncedSearch, scopeQuery, sort]);
  const params = useMemo(() => {
    const next = new URLSearchParams(filtros);
    next.set("limit", "25");
    next.set("offset", String(offset));
    return next.toString();
  }, [filtros, offset]);

  const { data, isLoading, error, refetch } = useAdjudicacionesEmpresa(empresaId, params);

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
      const rows = await todasLasAdjudicaciones(empresaId, filtros);

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
      const filas = [
        header,
        ...rows.map((row) => [
          row.fecha_adjudicacion,
          row.titulo ?? row.licitacion_id,
          row.organo_contratacion,
          row.cpv,
          row.ccaa,
          row.presupuesto_licitacion,
          row.importe_adjudicado,
          row.baja_pct,
          row.n_ofertas_recibidas,
        ]),
      ];
      // `descargarBlob` en vez de un ancla propia: el fichero se compone en el
      // cliente y no pasa por `/exports/download`, que es el único sitio donde
      // se emitía el evento de exportación. `empresaId` no viaja a la métrica.
      descargarBlob(
        `adjudicaciones-empresa-${empresaId}.csv`,
        csvBlob(filas),
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
              ) : !data?.items?.length ? (
                <TableRow>
                  <TableCell colSpan={6} className="h-28 text-center text-muted-foreground">
                    No hay adjudicaciones que coincidan con estos filtros.
                  </TableCell>
                </TableRow>
              ) : (
                data.items.map((award) => (
                  <TableRow key={award.licitacion_id}>
                    <TableCell className="min-w-72">
                      <EnlaceFicha
                        idExterno={award.licitacion_id}
                        className="font-medium transition-colors hover:text-primary"
                      >
                        {truncate(award.titulo ?? award.licitacion_id, 82)}
                      </EnlaceFicha>
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
