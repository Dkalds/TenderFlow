"use client";

/**
 * Las dos tablas de contexto de UTEs: con quién se asocia cada empresa, y qué
 * separa a una UTE de un contrato individual.
 *
 * Los pares de socios son co-licitación real —empresas que firmaron la misma
 * UTE—, no co-ocurrencia geográfica, y el pie de la tabla lo dice: sin esa
 * frase el lector puede leer una relación que el dato no afirma.
 */

import { Panel, PanelEmpty, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatCurrency, formatNumber, truncate } from "@/lib/utils";

import type { ComparativaRow, SocioPar } from "../_hooks/utes-types";

export function UtesSocios({
  socios,
  isLoading,
}: {
  socios: SocioPar[] | undefined;
  isLoading: boolean;
}) {
  return (
    <Panel>
      <PanelTitle title="Socios frecuentes" hint="Quién se asocia con quién" />
      {isLoading ? (
        <Skeleton className="h-[200px] w-full" />
      ) : socios && socios.length > 0 ? (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Empresa</TableHead>
                <TableHead>Socio</TableHead>
                <TableHead className="text-right">UTE juntas</TableHead>
                <TableHead className="text-right">Importe conjunto</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {socios.map((s, idx) => (
                <TableRow key={idx}>
                  <TableCell className="font-medium">{truncate(s.empresa_a, 35)}</TableCell>
                  <TableCell className="font-medium">{truncate(s.empresa_b, 35)}</TableCell>
                  <TableCell numeric>{formatNumber(s.contratos)}</TableCell>
                  <TableCell numeric>{formatCurrency(s.importe)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="mt-3 border-t border-border/60 pt-3 text-tf-meta text-muted-foreground">
            Pares de empresas que han firmado juntas una UTE: licitaron juntas de verdad, no solo coinciden en la
            misma zona.
          </p>
        </>
      ) : (
        <PanelEmpty
          title="Ningún par de socios"
          hint="Ninguna pareja de empresas ha firmado una UTE junta en el ámbito actual."
        />
      )}
    </Panel>
  );
}

export function UtesComparativa({
  filas,
  isLoading,
}: {
  filas: ComparativaRow[];
  isLoading: boolean;
}) {
  return (
    <Panel>
      <PanelTitle title="UTE frente a contrato en solitario" />
      {isLoading ? (
        <Skeleton className="h-[120px] w-full" />
      ) : filas.length > 0 ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Métrica</TableHead>
              <TableHead className="text-right">En UTE</TableHead>
              <TableHead className="text-right">En solitario</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filas.map((row) => (
              <TableRow key={row.metrica}>
                <TableCell className="font-medium">{row.metrica}</TableCell>
                <TableCell numeric>{row.ute}</TableCell>
                <TableCell numeric>{row.individual}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : (
        <PanelEmpty title="Sin comparativa" hint="No hay contratos suficientes en el ámbito actual para comparar." />
      )}
    </Panel>
  );
}
