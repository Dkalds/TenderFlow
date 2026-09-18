"use client";

/**
 * Las dos tablas de Clusters: el resumen (una fila por cluster, y la fila es el
 * selector del drill-down) y el detalle del cluster elegido.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Pista } from "@/components/ui/pista";
import { SkeletonTable } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatCurrency, formatNumber, truncate } from "@/lib/utils";

import type { ClusterEntry } from "../_hooks/use-clusters-view";

const TH = "pb-2 pr-4 font-medium text-muted-foreground";
const TH_NUM = "pb-2 pr-4 text-right font-medium text-muted-foreground";

export function ClustersResumenTabla({
  clusters,
  isLoading,
  onSelect,
}: {
  clusters: ClusterEntry[];
  isLoading: boolean;
  onSelect: (clusterId: number) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Resumen de clusters</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <SkeletonTable rows={6} />
        ) : (
          <div className="overflow-x-auto">
            <Table className="w-full text-sm">
              <TableHeader>
                <TableRow className="border-b text-left">
                  <TableHead className={TH}>ID</TableHead>
                  <TableHead className={TH}>Keywords</TableHead>
                  <TableHead className={TH}>CPV dominante</TableHead>
                  <TableHead className={TH}>Órgano dominante</TableHead>
                  <TableHead className={TH_NUM}>Licitaciones</TableHead>
                  <TableHead className={TH_NUM}>Importe medio</TableHead>
                  <TableHead className="pb-2 text-right font-medium text-muted-foreground">
                    Importe total
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {clusters.map((c) => (
                  <TableRow
                    key={c.cluster_id}
                    className="cursor-pointer border-b border-border/50 hover:bg-muted/50"
                    onClick={() => onSelect(c.cluster_id)}
                  >
                    <TableCell className="py-2 pr-4 tabular-nums">{c.cluster_id}</TableCell>
                    {/* `Pista` y no `title`: se ve al pasar el puntero y la
                        tabla no gana paradas de tabulación. */}
                    <TableCell className="max-w-md py-2 pr-4">
                      <Pista contenido={c.label}>
                        <span className="block truncate">{c.label}</span>
                      </Pista>
                    </TableCell>
                    <TableCell className="max-w-[14rem] py-2 pr-4 text-muted-foreground">
                      <Pista contenido={c.cpv_dominante}>
                        <span className="block truncate">{c.cpv_dominante ?? "-"}</span>
                      </Pista>
                    </TableCell>
                    <TableCell className="max-w-[12rem] py-2 pr-4 text-muted-foreground">
                      <Pista contenido={c.organo_dominante}>
                        <span className="block truncate">{c.organo_dominante ?? "-"}</span>
                      </Pista>
                    </TableCell>
                    <TableCell className="py-2 pr-4 text-right tabular-nums">{formatNumber(c.n)}</TableCell>
                    <TableCell className="py-2 pr-4 text-right tabular-nums">{formatCurrency(c.importe_medio)}</TableCell>
                    <TableCell className="py-2 text-right tabular-nums">{formatCurrency(c.importe_total)}</TableCell>
                  </TableRow>
                ))}
                {clusters.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                      Sin clusters
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function ClusterDetalleTabla({
  clusters,
  selected,
  onSelect,
}: {
  clusters: ClusterEntry[];
  selected: ClusterEntry;
  onSelect: (clusterId: number) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Licitaciones del cluster</CardTitle>
        <div className="mt-2">
          <Select
            value={String(selected.cluster_id)}
            onValueChange={(v) => onSelect(Number(v))}
          >
            <SelectTrigger className="w-full max-w-xl text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {clusters.map((c) => (
                <SelectItem key={c.cluster_id} value={String(c.cluster_id)}>
                  Cluster {c.cluster_id}: {truncate(c.label, 50)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <Table className="w-full text-sm">
            <TableHeader>
              <TableRow className="border-b text-left">
                <TableHead className={TH}>Título</TableHead>
                <TableHead className={TH}>Órgano</TableHead>
                <TableHead className={TH_NUM}>Importe</TableHead>
                <TableHead className={TH}>CCAA</TableHead>
                <TableHead className="pb-2 font-medium text-muted-foreground">Estado</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {selected.items.map((it) => (
                <TableRow key={it.id_externo} className="border-b border-border/50 hover:bg-muted/50">
                  <TableCell className="max-w-sm py-2 pr-4 font-medium">
                    <Pista contenido={it.titulo}>
                      <span className="line-clamp-2">{it.titulo ?? "-"}</span>
                    </Pista>
                  </TableCell>
                  <TableCell className="max-w-[12rem] py-2 pr-4">
                    <Pista contenido={it.organo_contratacion}>
                      <span className="block truncate">{it.organo_contratacion ?? "-"}</span>
                    </Pista>
                  </TableCell>
                  <TableCell className="py-2 pr-4 text-right tabular-nums">
                    {it.importe != null ? formatCurrency(it.importe) : "-"}
                  </TableCell>
                  <TableCell className="py-2 pr-4">{it.ccaa ?? "-"}</TableCell>
                  <TableCell className="py-2">{it.estado ?? "-"}</TableCell>
                </TableRow>
              ))}
              {selected.items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                    Sin licitaciones
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}
