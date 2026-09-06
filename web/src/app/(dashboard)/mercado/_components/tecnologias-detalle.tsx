"use client";

/**
 * Detalle por tecnología: el selector, sus tres KPIs y la tabla de licitaciones
 * de la tecnología elegida.
 *
 * Sin selección no se pide nada ni se pinta una tabla vacía: se dice qué hacer.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { KpiCard } from "@/components/charts/kpi-card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatCurrency, formatDate, formatNumber } from "@/lib/utils";
import { valorOEmpty } from "@/lib/cobertura";
import { Filter, Hash, DollarSign, TrendingUp } from "lucide-react";

import type { DetalleResponse, TecnologiaItem } from "../_hooks/use-tecnologias-view";

const TH = "pb-2 pr-4 font-medium text-muted-foreground";

export function TecnologiasDetalle({
  items,
  selectedTech,
  onSelectTech,
  detalle,
  isLoading,
}: {
  items: TecnologiaItem[];
  selectedTech: string;
  onSelectTech: (tecnologia: string) => void;
  detalle: DetalleResponse | undefined;
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Filter className="h-4 w-4" />
          Detalle por tecnología
        </CardTitle>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <Select
            value={selectedTech || "__all__"}
            onValueChange={(v) => onSelectTech(v === "__all__" ? "" : v)}
          >
            <SelectTrigger className="w-56 text-sm">
              <SelectValue placeholder="Selecciona una tecnología" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">Selecciona una tecnología</SelectItem>
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
      </CardHeader>
      <CardContent>
        {!selectedTech ? (
          <p className="py-8 text-center text-muted-foreground">
            Selecciona una tecnología para ver sus licitaciones.
          </p>
        ) : isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-3">
              <KpiCard title="Licitaciones" value={formatNumber(detalle?.n ?? 0)} icon={Hash} />
              <KpiCard
                title="Importe total"
                value={valorOEmpty(detalle?.importe_total, formatCurrency)}
                icon={DollarSign}
              />
              <KpiCard
                title="Importe medio"
                value={valorOEmpty(detalle?.importe_medio, formatCurrency)}
                icon={TrendingUp}
              />
            </div>
            <div className="overflow-x-auto">
              <Table className="w-full text-sm">
                <TableHeader>
                  <TableRow className="border-b text-left">
                    <TableHead className={TH}>Título</TableHead>
                    <TableHead className={TH}>Órgano</TableHead>
                    <TableHead className={`${TH} text-right`}>Importe</TableHead>
                    <TableHead className={TH}>Estado</TableHead>
                    <TableHead className={TH}>CCAA</TableHead>
                    <TableHead className="pb-2 font-medium text-muted-foreground">Publicación</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(detalle?.items ?? []).map((it) => (
                    <TableRow key={it.id_externo} className="border-b border-border/50 hover:bg-muted/50">
                      <TableCell className="max-w-sm py-2 pr-4 font-medium">
                        <span className="line-clamp-2" title={it.titulo ?? ""}>{it.titulo ?? "-"}</span>
                      </TableCell>
                      <TableCell className="max-w-[12rem] truncate py-2 pr-4" title={it.organo_contratacion ?? ""}>
                        {it.organo_contratacion ?? "-"}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {it.importe != null ? formatCurrency(it.importe) : "-"}
                      </TableCell>
                      <TableCell className="py-2 pr-4">{it.estado ?? "-"}</TableCell>
                      <TableCell className="py-2 pr-4">{it.ccaa ?? "-"}</TableCell>
                      <TableCell className="py-2 tabular-nums">
                        {it.fecha_publicacion ? formatDate(it.fecha_publicacion) : "-"}
                      </TableCell>
                    </TableRow>
                  ))}
                  {(detalle?.items ?? []).length === 0 && (
                    <TableRow>
                      <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">
                        Sin licitaciones
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
