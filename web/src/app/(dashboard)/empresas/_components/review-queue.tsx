"use client";

/**
 * Cola de revisión de matches dudosos del resolutor de empresas.
 *
 * Cada fila es una decisión humana con dos salidas: unir al candidato o crear
 * una empresa nueva. No hay «más tarde»: lo que no se resuelve sigue restando
 * cobertura al importe enlazado.
 */

import { Check, ShieldQuestion, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useRevisionesEmpresas } from "../_hooks/use-revisiones-empresas";

export function ReviewQueue() {
  const { items, resolve } = useRevisionesEmpresas();
  if (items.length === 0) return null;

  return (
    <Card className="border-amber-500/40">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldQuestion className="h-4 w-4 text-amber-500" />
          Revisión de matches dudosos
        </CardTitle>
        <CardDescription>
          El resolutor no enlaza automáticamente nombres casi idénticos o NIFs en conflicto.
          ¿Es la misma empresa? <Check className="inline h-3 w-3" /> la une al candidato;{" "}
          <X className="inline h-3 w-3" /> crea una empresa nueva.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Visto en fuente</TableHead>
              <TableHead>Candidato existente</TableHead>
              <TableHead className="text-right">Similitud</TableHead>
              <TableHead className="w-28 text-right">Decisión</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="max-w-[260px]">
                  <span className="block truncate text-sm">{r.nombre_original}</span>
                  {r.nif && (
                    <span className="font-mono text-xs text-muted-foreground">{r.nif}</span>
                  )}
                </TableCell>
                <TableCell className="max-w-[260px]">
                  <span className="block truncate text-sm">{r.candidato_nombre ?? "—"}</span>
                  {r.candidato_nif && (
                    <span className="font-mono text-xs text-muted-foreground">
                      {r.candidato_nif}
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-right font-mono text-sm">
                  {(r.score * 100).toFixed(0)}%
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Misma empresa (unir al candidato)"
                      disabled={resolve.isPending}
                      onClick={() => resolve.mutate({ id: r.id, accept: true })}
                    >
                      <Check className="h-4 w-4 text-green-600" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Empresa distinta (crear nueva)"
                      disabled={resolve.isPending}
                      onClick={() => resolve.mutate({ id: r.id, accept: false })}
                    >
                      <X className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
