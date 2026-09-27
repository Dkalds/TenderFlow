"use client";

/**
 * Las dos tablas de Clusters: el resumen (una fila por cluster, y la fila es el
 * selector del drill-down) y el detalle del cluster elegido.
 */

import { Panel, PanelTitle } from "@/components/console/panel";
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
import { EMPTY, formatCurrency, formatNumber, truncate } from "@/lib/utils";

import type { ClusterEntry } from "../_hooks/use-clusters-view";

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
    <Panel>
      <PanelTitle title="Resumen de clusters" hint="Elige uno para ver sus licitaciones" />
      {isLoading ? (
        <SkeletonTable rows={6} />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>Palabras clave</TableHead>
              <TableHead>CPV dominante</TableHead>
              <TableHead>Órgano dominante</TableHead>
              <TableHead className="text-right">Licitaciones</TableHead>
              <TableHead className="text-right">Importe medio</TableHead>
              <TableHead className="text-right">Importe total</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {clusters.map((c) => (
              <TableRow key={c.cluster_id} className="cursor-pointer" onClick={() => onSelect(c.cluster_id)}>
                <TableCell>{c.cluster_id}</TableCell>
                {/* El nombre del cluster es el botón: con el ratón vale toda la
                    fila, y con el teclado se llega aquí. `Pista` y no `title`
                    para el nombre completo. */}
                <TableCell className="max-w-md">
                  <Pista contenido={c.label}>
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        onSelect(c.cluster_id);
                      }}
                      className="block max-w-full truncate text-left transition-colors hover:text-primary"
                    >
                      {c.label}
                    </button>
                  </Pista>
                </TableCell>
                <TableCell className="max-w-[14rem] text-muted-foreground">
                  <Pista contenido={c.cpv_dominante}>
                    <span className="block truncate">{c.cpv_dominante ?? EMPTY}</span>
                  </Pista>
                </TableCell>
                <TableCell className="max-w-[12rem] text-muted-foreground">
                  <Pista contenido={c.organo_dominante}>
                    <span className="block truncate">{c.organo_dominante ?? EMPTY}</span>
                  </Pista>
                </TableCell>
                <TableCell numeric>{formatNumber(c.n)}</TableCell>
                <TableCell numeric>{formatCurrency(c.importe_medio)}</TableCell>
                <TableCell numeric>{formatCurrency(c.importe_total)}</TableCell>
              </TableRow>
            ))}
            {clusters.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                  Ningún cluster con el ámbito actual.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      )}
    </Panel>
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
    <Panel>
      <PanelTitle title="Licitaciones del cluster" />
      <Select value={String(selected.cluster_id)} onValueChange={(v) => onSelect(Number(v))}>
        <SelectTrigger className="mb-3 w-full max-w-xl" aria-label="Cluster">
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
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Título</TableHead>
            <TableHead>Órgano</TableHead>
            <TableHead className="text-right">Importe</TableHead>
            <TableHead>CCAA</TableHead>
            <TableHead>Estado</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {selected.items.map((it) => (
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
              <TableCell>{it.ccaa ?? EMPTY}</TableCell>
              <TableCell>{it.estado ?? EMPTY}</TableCell>
            </TableRow>
          ))}
          {selected.items.length === 0 && (
            <TableRow>
              <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                Este cluster no tiene licitaciones con el ámbito actual.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </Panel>
  );
}
