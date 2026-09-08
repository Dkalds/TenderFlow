"use client";

import * as React from "react";
import { Check } from "lucide-react";
import { cn, formatNumber } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { PanelError } from "@/components/console/panel";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  filtrarPorConfianza,
  nifEnConflicto,
  SAFE_SCORE,
  type ConfidenceFilter,
  type ReviewItem,
} from "../_hooks/use-review-queue";

const GRID = "grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_140px_150px] items-center gap-4 px-5";

const FILTROS: { key: ConfidenceFilter; label: string }[] = [
  { key: "all", label: "Todos" },
  { key: "safe", label: "≥ 90 %" },
  { key: "doubt", label: "< 90 %" },
];

export interface ReviewQueueProps {
  items: ReviewItem[];
  loading: boolean;
  error: boolean;
  errorDetail?: string;
  onRetry: () => void;
  filtro: ConfidenceFilter;
  onFiltroChange: (filtro: ConfidenceFilter) => void;
  onDecidir: (ids: number[], accept: boolean, descripcion: string) => void;
}

export function ReviewQueue({
  items,
  loading,
  error,
  errorDetail,
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
        <PanelError
          title="No se pudo cargar la cola de revisión"
          detail={errorDetail ?? "GET /api/v1/empresas/reviews"}
          onRetry={onRetry}
        />
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-border/60 flex flex-none items-center gap-2 border-b px-5 py-3">
        <span className="text-tf-body text-muted-foreground">
          {items.length === 0
            ? "Sin matches pendientes"
            : `${formatNumber(visibles.length)} de ${formatNumber(items.length)} matches dudosos`}
        </span>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="border-border/70 text-tf-micro text-muted-foreground grid h-4 w-4 cursor-help place-items-center rounded-full border font-semibold">
              ?
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-[320px]">
            «Unir» enlaza el nombre visto en fuente al candidato existente. «Nueva» crea una empresa distinta. Cada
            decisión recalcula el importe resuelto y las cuotas de Competencia.
          </TooltipContent>
        </Tooltip>

        <div className="flex-1" />

        <div className="border-border/60 flex items-center gap-0.5 rounded-md border p-0.5">
          {FILTROS.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => onFiltroChange(item.key)}
              aria-pressed={filtro === item.key}
              className={cn(
                "tf-pressable text-tf-meta h-6 rounded px-2.5 font-medium transition-colors duration-140 ease-out",
                filtro === item.key ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>

        {seguros.length > 0 && !mostrarConfirmacion && (
          <button
            type="button"
            onClick={() => setConfirmando(true)}
            className="tf-pressable border-border/70 text-tf-meta text-foreground hover:border-primary/50 inline-flex h-[30px] items-center gap-1.5 rounded-md border px-3 font-medium transition-colors"
          >
            <Check className="h-3 w-3" aria-hidden="true" />
            Unir los ≥ 90 % ({seguros.length})
          </button>
        )}
      </div>

      {/* Confirmación explícita antes del lote: una decisión suelta se deshace
          desde el toast, pero unir veinte de golpe reescribe una parte del
          maestro de una vez, y eso se pregunta antes. */}
      {mostrarConfirmacion && (
        <div className="border-primary/30 bg-primary/8 flex flex-none items-center gap-3 border-b px-5 py-2.5">
          <span className="text-tf-body font-medium">
            Unir {seguros.length} matches con similitud ≥ 90 % a sus candidatos. Se recalculan importe resuelto y
            cuotas.
          </span>
          <div className="flex-1" />
          <button
            type="button"
            onClick={() => setConfirmando(false)}
            className="tf-pressable border-border/70 text-tf-meta text-muted-foreground hover:text-foreground h-7 rounded-md border px-3 font-medium"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={() => {
              setConfirmando(false);
              onDecidir(
                seguros.map((item) => item.id),
                true,
                `${seguros.length} matches unidos · importe resuelto recalculado`,
              );
            }}
            className="tf-pressable bg-primary text-tf-meta text-primary-foreground h-7 rounded-md px-3 font-semibold"
          >
            Unir todos
          </button>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div
          className={cn(
            GRID,
            "border-border/70 bg-background text-tf-micro text-muted-foreground sticky top-0 z-10 h-[34px] border-b font-medium",
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
          <div className="px-6 py-20 text-center">
            <Check className="mx-auto mb-3 h-5 w-5 text-[hsl(var(--success))]" aria-hidden="true" />
            <p className="text-tf-body text-foreground mb-1.5 font-medium">
              {items.length === 0 ? "Cola vacía" : "Nada en este filtro"}
            </p>
            <p className="text-tf-meta text-muted-foreground mx-auto max-w-[44ch]">
              {items.length === 0
                ? "Todo adjudicatario nuevo se ha resuelto automáticamente a una entidad del maestro."
                : "Cambia el filtro de confianza para ver el resto de la cola."}
            </p>
          </div>
        ) : (
          visibles.map((item) => {
            const conflicto = nifEnConflicto(item);
            const score = Math.round((item.score ?? 0) * 100);
            return (
              <div key={item.id} className={cn(GRID, "border-border/25 hover:bg-muted-foreground/5 h-[52px] border-b")}>
                <div className="min-w-0">
                  <div className="text-tf-body text-foreground truncate font-medium">{item.nombre_original ?? "—"}</div>
                  <div className="text-tf-meta text-muted-foreground mt-0.5 font-mono">
                    {item.nif ?? "sin NIF en fuente"}
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
                  <span className="tf-tnum text-tf-meta text-muted-foreground w-8 text-right font-mono font-medium">
                    {score}%
                  </span>
                </div>
                <div className="flex justify-end gap-1.5">
                  {/* Con texto y no con ✓/✕: en una cola donde cada clic
                      reescribe el maestro, saber qué hace el botón no puede
                      depender de dejar el ratón quieto encima. */}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        onClick={() =>
                          onDecidir([item.id], true, `Unida a «${item.candidato_nombre ?? "—"}»`)
                        }
                        className="tf-pressable border-border/70 text-tf-meta text-foreground hover:border-primary/50 h-7 rounded-md border px-2.5 font-medium transition-colors"
                      >
                        Unir
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>Misma empresa: unir al candidato</TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        onClick={() =>
                          onDecidir(
                            [item.id],
                            false,
                            `Creada como empresa nueva · «${item.nombre_original ?? "—"}»`
                          )
                        }
                        className="tf-pressable text-tf-meta text-muted-foreground hover:border-border/70 hover:text-foreground h-7 rounded-md border border-transparent px-2.5 font-medium transition-colors"
                      >
                        Nueva
                      </button>
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
