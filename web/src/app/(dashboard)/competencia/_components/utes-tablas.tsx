"use client";

/**
 * Las dos tablas de contexto de UTEs: con quién se asocia cada empresa, y qué
 * separa a una UTE de un contrato individual.
 *
 * Los pares de socios son co-licitación real —empresas que firmaron la misma
 * UTE—, no co-ocurrencia geográfica, y el pie de la tabla lo dice: sin esa
 * frase el lector puede leer una relación que el dato no afirma.
 */

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatCurrency, formatNumber, truncate } from "@/lib/utils";
import { Building2, Handshake } from "lucide-react";

import type { ComparativaRow, SocioPar } from "../_hooks/utes-types";

export function UtesSocios({
  socios,
  isLoading,
}: {
  socios: SocioPar[] | undefined;
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Handshake className="h-4 w-4" />
          Socios Frecuentes (quién se asocia con quién)
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[200px] w-full" />
        ) : socios && socios.length > 0 ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="text-left text-muted-foreground">
                  <TableHead>Empresa</TableHead>
                  <TableHead>Socio</TableHead>
                  <TableHead>UTEs juntas</TableHead>
                  <TableHead>Importe conjunto</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {socios.map((s, idx) => (
                  <TableRow key={idx}>
                    <TableCell className="font-medium">{truncate(s.empresa_a, 35)}</TableCell>
                    <TableCell className="font-medium">{truncate(s.empresa_b, 35)}</TableCell>
                    <TableCell className="tabular-nums">{formatNumber(s.contratos)}</TableCell>
                    <TableCell className="tabular-nums">{formatCurrency(s.importe)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Separator className="my-3" />
            <p className="text-xs text-muted-foreground">
              Pares de empresas que han formado UTE conjunta (co-licitacion real,
              no co-ocurrencia geografica).
            </p>
          </div>
        ) : (
          <p className="py-8 text-center text-muted-foreground">
            Sin pares de co-licitación detectados
          </p>
        )}
      </CardContent>
    </Card>
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
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Building2 className="h-4 w-4" />
          Comparativa UTE vs Individual
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[120px] w-full" />
        ) : filas.length > 0 ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="text-left text-muted-foreground">
                  <TableHead>Métrica</TableHead>
                  <TableHead>
                    <span className="inline-flex items-center gap-1">
                      <Badge variant="default" className="text-xs">UTE</Badge>
                    </span>
                  </TableHead>
                  <TableHead>
                    <span className="inline-flex items-center gap-1">
                      <Badge variant="secondary" className="text-xs">Individual</Badge>
                    </span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filas.map((row) => (
                  <TableRow key={row.metrica}>
                    <TableCell className="font-medium">{row.metrica}</TableCell>
                    <TableCell className="tabular-nums">{row.ute}</TableCell>
                    <TableCell className="tabular-nums">{row.individual}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="py-8 text-center text-muted-foreground">Sin datos comparativos disponibles</p>
        )}
      </CardContent>
    </Card>
  );
}
