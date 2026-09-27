"use client";

import * as React from "react";
import { Check, CircleHelp } from "lucide-react";
import { cn, formatNumber } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Aviso, PanelEmpty, PanelError, Segmented } from "@/components/console/panel";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  filtrarPorConfianza,
  nifEnConflicto,
  SAFE_SCORE,
  type ConfidenceFilter,
  type ReviewItem,
} from "../_hooks/use-review-queue";

const GRID = "grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_140px_150px] items-center gap-4 px-5";

const FILTROS: { value: ConfidenceFilter; label: string }[] = [
  { value: "all", label: "Todos" },
  { value: "safe", label: "≥ 90 %" },
  { value: "doubt", label: "< 90 %" },
];

export interface ReviewQueueProps {
  items: ReviewItem[];
  loading: boolean;
  /**
   * El fallo de la consulta, si lo hubo. Da el mensaje y el detalle técnico
   * (estado y ruta, plegados) de `PanelError`.
   */
  error?: unknown;
  onRetry: () => void;
  filtro: ConfidenceFilter;
  onFiltroChange: (filtro: ConfidenceFilter) => void;
  onDecidir: (ids: number[], accept: boolean, descripcion: string) => void;
}

export function ReviewQueue({
  items,
  loading,
  error,
  onRetry,
  filtro,
  onFiltroChange,
  onDecidir,
}: ReviewQueueProps) {
  const [confirmando, setConfirmando] = React.useState(false);
  const visibles = filtrarPorConfianza(items, filtro);
  const seguros = items.filter((item) => (item.score ?? 0) >= SAFE_SCORE);
  // Derivado y no un estado que haya que apagar: cuando el lote se resuelve ya
  // no quedan matches seguros, así que la barra desaparece sola.
  const mostrarConfirmacion = confirmando && seguros.length > 0;

  if (error) {
    return (
      <div className="p-5">
        <PanelError title="No se pudo cargar la cola de revisión" error={error} onRetry={onRetry} />
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-border/60 flex flex-none items-center gap-2 border-b px-5 py-3">
        <span className="text-tf-body text-muted-foreground">
          {items.length === 0
            ? "Sin coincidencias pendientes"
            : `${formatNumber(visibles.length)} de ${formatNumber(items.length)} coincidencias dudosas`}
        </span>
        {/* Un botón de verdad: el «?» era un `span` que solo abría con el
            ratón, y la explicación de qué hace cada botón tiene que llegar
            también con teclado. */}
        <Tooltip>
          <TooltipTrigger
            type="button"
            className="text-muted-foreground/70 hover:text-foreground -m-1 inline-flex size-6 items-center justify-center rounded-full transition-colors"
          >
            <CircleHelp className="size-3.5" aria-hidden="true" />
            <span className="sr-only">Qué hacen Unir y Nueva</span>
          </TooltipTrigger>
          <TooltipContent className="max-w-[320px]">
            «Unir» enlaza el nombre visto en fuente al candidato existente. «Nueva» crea una empresa distinta. Cada
            decisión recalcula el importe resuelto y las cuotas de Competencia.
          </TooltipContent>
        </Tooltip>

        <div className="flex-1" />

        <Segmented
          aria-label="Filtrar por similitud"
          value={filtro}
          onChange={onFiltroChange}
          options={FILTROS}
        />

        {seguros.length > 0 && !mostrarConfirmacion && (
          <Button type="button" variant="outline" size="sm" onClick={() => setConfirmando(true)}>
            <Check aria-hidden="true" />
            Unir los ≥ 90 % ({seguros.length})
          </Button>
        )}
      </div>

      {/* Confirmación explícita antes del lote: una decisión suelta se deshace
          desde el toast, pero unir veinte de golpe reescribe una parte del
          maestro de una vez, y eso se pregunta antes. */}
      {mostrarConfirmacion && (
        <Aviso
          variant="banda"
          tone="info"
          className="flex-none px-5 py-2.5"
          action={
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" size="sm" onClick={() => setConfirmando(false)}>
                Cancelar
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={() => {
                  setConfirmando(false);
                  onDecidir(
                    seguros.map((item) => item.id),
                    true,
                    `${seguros.length} coincidencias unidas · importe resuelto recalculado`,
                  );
                }}
              >
                Unir todos
              </Button>
            </div>
          }
        >
          <span className="text-tf-body font-medium">
            Unir {seguros.length} coincidencias con similitud ≥ 90 % a sus candidatos. Se recalculan importe resuelto y
            cuotas.
          </span>
        </Aviso>
      )}

      <div className="relative min-h-0 flex-1 overflow-y-auto">
        <div
          className={cn(
            GRID,
            CABECERA_COLUMNA,
            "border-border/70 bg-background sticky top-0 z-10 h-[34px] border-b",
          )}
        >
          <span>Visto en fuente</span>
          <span>Candidato existente</span>
          <span>Similitud</span>
          <span className="text-right">Decisión</span>
        </div>

        {loading ? (
          <div className="flex flex-col gap-2 px-5 py-2.5">
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} className="h-8 w-full rounded-md" />
            ))}
          </div>
        ) : visibles.length === 0 ? (
          <PanelEmpty
            className="py-20"
            title={items.length === 0 ? "Cola vacía" : "Nada en este filtro"}
            hint={
              items.length === 0
                ? "Todo adjudicatario nuevo se ha resuelto automáticamente a una entidad del maestro."
                : "Cambia el filtro de similitud para ver el resto de la cola."
            }
          />
        ) : (
          visibles.map((item) => {
            const conflicto = nifEnConflicto(item);
            const score = Math.round((item.score ?? 0) * 100);
            return (
              <div key={item.id} className={cn(GRID, "border-border/30 hover:bg-primary/5 h-[52px] border-b transition-colors")}>
                <div className="min-w-0">
                  <div className="text-tf-body text-foreground truncate font-medium">{item.nombre_original ?? "—"}</div>
                  <div className={cn("text-tf-meta text-muted-foreground mt-0.5", item.nif && "font-mono")}>
                    {item.nif ?? "Sin NIF en fuente"}
                  </div>
                </div>
                <div className="min-w-0">
                  <div className="text-tf-body text-foreground truncate font-medium">
                    {item.candidato_nombre ?? "—"}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5">
                    <span
                      className={cn("text-tf-meta font-mono", conflicto ? "text-destructive" : "text-muted-foreground")}
                    >
                      {item.candidato_nif ?? "—"}
                    </span>
                    {conflicto && <span className="text-tf-micro text-destructive font-medium">NIF distinto</span>}
                  </div>
                </div>
                {/* Barra neutra: la similitud informa, no alarma. */}
                <div className="flex items-center gap-2">
                  <span className="bg-muted-foreground/15 block h-1 flex-1 overflow-hidden rounded-sm">
                    <span className="bg-muted-foreground/60 block h-full" style={{ width: `${score}%` }} />
                  </span>
                  <span className="tf-tnum text-tf-meta text-muted-foreground w-8 text-right font-medium">
                    {score}%
                  </span>
                </div>
                <div className="flex justify-end gap-1.5">
                  {/* Con texto y no con ✓/✕: en una cola donde cada clic
                      reescribe el maestro, saber qué hace el botón no puede
                      depender de dejar el ratón quieto encima. */}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          onDecidir([item.id], true, `Unida a «${item.candidato_nombre ?? "—"}»`)
                        }
                      >
                        Unir
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Misma empresa: unir al candidato</TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="text-muted-foreground"
                        onClick={() =>
                          onDecidir(
                            [item.id],
                            false,
                            `Creada como empresa nueva · «${item.nombre_original ?? "—"}»`
                          )
                        }
                      >
                        Nueva
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Empresa distinta: crear nueva</TooltipContent>
                  </Tooltip>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
