"use client";

/**
 * Horizonte — renovaciones a 3-24 meses con el CTA de anticipar.
 *
 * Tercera vista de Mi Pipeline (`?vista=horizonte`). El cuerpo vive aquí y no
 * en `(dashboard)/renovaciones/page.tsx` porque `/renovaciones` redirige 308 a
 * `/mi-pipeline?vista=horizonte` y los redirects de Next corren antes que el
 * enrutado por sistema de ficheros: aquel `page.tsx` no se ejecutaba nunca como
 * ruta y sin embargo el espacio lo montaba como componente, sin el contrato
 * `params`/`searchParams`. Mismo reparto que `agenda-view` y `embudo-view`.
 *
 * Los enlaces guardados los preserva el 308, no el fichero de ruta; el alias
 * `?vista=renovaciones` lo traduce `mi-pipeline/page.tsx`.
 *
 * Datos, filtros y acciones viven en `_hooks/use-horizonte.ts`; las piezas de
 * pantalla, en `_components/horizonte/`, igual que la agenda. Aquí queda el
 * reparto de la pantalla, el selector de ventana y el estado de error, que es
 * el único que sustituye a todo lo demás.
 */

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PipelineRoleNav } from "@/components/pipeline-role-nav";
import { HORIZONTES, useHorizonte } from "../_hooks/use-horizonte";
import { HorizonteCartera } from "./horizonte/horizonte-cartera";
import { HorizonteKpis } from "./horizonte/horizonte-kpis";
import { HorizonteLista } from "./horizonte/horizonte-lista";

export default function HorizonteView() {
  const horizonte = useHorizonte();

  if (horizonte.error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
        <p className="text-destructive">Error: {(horizonte.error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-[70ch] text-xs text-muted-foreground">
          Contratos adjudicados que vencen pronto: o los defiende el adjudicatario actual o se los disputa
          quien llegue primero.
        </p>
        <Select value={horizonte.meses} onValueChange={horizonte.setMeses}>
          <SelectTrigger className="w-[140px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {HORIZONTES.map((h) => (
              <SelectItem key={h.value} value={h.value}>
                {h.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <PipelineRoleNav current="renovaciones" />

      <HorizonteKpis totales={horizonte.totales} />

      <HorizonteCartera
        meses={horizonte.meses}
        topCartera={horizonte.topCartera}
        isLoading={horizonte.isLoading}
      />

      <HorizonteLista
        items={horizonte.items}
        isLoading={horizonte.isLoading}
        empresaSearch={horizonte.empresaSearch}
        onEmpresaSearchChange={horizonte.setEmpresaSearch}
        maxScore={horizonte.maxScore}
        onAnticipar={(licitacionId) => void horizonte.anticipar(licitacionId)}
        onAbrirDetalle={horizonte.abrirDetalle}
      />
    </div>
  );
}
