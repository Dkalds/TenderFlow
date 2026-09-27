"use client";

/**
 * Detalle por tecnología: el selector, sus tres KPIs y la tabla de licitaciones
 * de la tecnología elegida.
 *
 * Sin selección no se pide nada ni se pinta una tabla vacía: se dice qué hacer.
 */

import {
  Panel,
  PanelEmpty,
  PanelError,
  PanelTitle,
  StatCell,
  StatStrip,
} from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Pista } from "@/components/ui/pista";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EMPTY, formatCurrency, formatDate, formatNumber } from "@/lib/utils";
import { valorOEmpty } from "@/lib/cobertura";

import type { DetalleResponse, TecnologiaItem } from "../_hooks/use-tecnologias-view";

export function TecnologiasDetalle({
  items,
  selectedTech,
  onSelectTech,
  detalle,
  isLoading,
  error,
  onRetry,
}: {
  items: TecnologiaItem[];
  selectedTech: string;
  onSelectTech: (tecnologia: string) => void;
  detalle: DetalleResponse | undefined;
  isLoading: boolean;
  /** El fallo de la consulta del detalle: se dice, no se pinta una tabla vacía. */
  error?: unknown;
  onRetry?: () => void;
}) {
  const filas = detalle?.items ?? [];
  return (
    <Panel>
      <PanelTitle title="Detalle por tecnología" />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Select
          value={selectedTech || "__all__"}
          onValueChange={(v) => onSelectTech(v === "__all__" ? "" : v)}
        >
          <SelectTrigger className="w-56" aria-label="Tecnología">
            <SelectValue placeholder="Elige una tecnología" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Elige una tecnología</SelectItem>
            {items.map((t) => (
              <SelectItem key={t.tecnologia} value={t.tecnologia}>
                {t.tecnologia}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {selectedTech && (
          <Button variant="ghost" size="sm" onClick={() => onSelectTech("")}>
            Limpiar
          </Button>
        )}
      </div>
      {!selectedTech ? (
        <PanelEmpty
          title="Ninguna tecnología elegida"
          hint="Elige una arriba para ver sus cifras y sus licitaciones."
        />
      ) : isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : error ? (
        <PanelError title={`No se pudo cargar el detalle de ${selectedTech}`} error={error} onRetry={onRetry} />
      ) : (
        <div className="space-y-4">
          <StatStrip columns={3}>
            <StatCell label="Licitaciones" value={formatNumber(detalle?.n ?? 0)} />
            <StatCell label="Importe total" value={valorOEmpty(detalle?.importe_total, formatCurrency)} />
            <StatCell label="Importe medio" value={valorOEmpty(detalle?.importe_medio, formatCurrency)} />
          </StatStrip>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Título</TableHead>
                <TableHead>Órgano</TableHead>
                <TableHead className="text-right">Importe</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>CCAA</TableHead>
                <TableHead>Publicación</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filas.map((it) => (
                <TableRow key={it.id_externo}>
                  <TableCell className="max-w-sm font-medium">
                    <Pista contenido={it.titulo}>
                      <span className="line-clamp-2">{it.titulo ?? EMPTY}</span>
                    </Pista>
                  </TableCell>
                  <TableCell className="max-w-[12rem]">
                    <Pista contenido={it.organo_contratacion}>
                      <span className="block truncate">{it.organo_contratacion ?? EMPTY}</span>
                    </Pista>
                  </TableCell>
                  <TableCell numeric>{it.importe != null ? formatCurrency(it.importe) : EMPTY}</TableCell>
                  <TableCell>{it.estado ?? EMPTY}</TableCell>
                  <TableCell>{it.ccaa ?? EMPTY}</TableCell>
                  <TableCell className="whitespace-nowrap">
                    {it.fecha_publicacion ? formatDate(it.fecha_publicacion) : EMPTY}
                  </TableCell>
                </TableRow>
              ))}
              {filas.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">
                    {selectedTech} no tiene licitaciones en el ámbito actual.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      )}
    </Panel>
  );
}
