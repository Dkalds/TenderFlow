"use client";

/**
 * La cronología del contrato seleccionado, dentro del inspector de Cartera.
 *
 * `GET /pursuits/cartera/{id}/eventos` cuenta qué le pasó al contrato
 * **después** de ganarlo: adjudicación, formalización, modificaciones de
 * importe, prórrogas, anulación. Es lo que explica las dos cifras que la tabla
 * enseña sin justificar —por qué hay tres prórrogas y por qué la fecha de fin
 * se movió—, y hasta ahora no había forma de verlo desde el producto.
 *
 * El orden y el texto de cada evento vienen de la API; aquí no se agrupa, no
 * se cuenta y no se deriva nada. `importe_delta_eur` sólo llega en las
 * modificaciones de importe, así que su ausencia no se pinta como un cero.
 */
import { PanelError } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { TIPO_EVENTO_LABELS } from "@/components/eventos-timeline";
import { useCarteraEventos } from "@/hooks/use-cartera";
import { fechaCorta } from "@/lib/adjudicacion-prevista";
import { cn, formatCompactCurrency } from "@/lib/utils";

export function CarteraEventos({ carteraId }: { carteraId: number }) {
  const { data, isPending, error, refetch } = useCarteraEventos(carteraId);

  if (isPending) {
    return (
      <div className="space-y-1.5" role="status" aria-label="Cargando la cronología del contrato">
        <Skeleton className="h-4 w-3/4 rounded-sm" />
        <Skeleton className="h-4 w-2/3 rounded-sm" />
        <Skeleton className="h-4 w-1/2 rounded-sm" />
      </div>
    );
  }

  if (error) {
    return (
      <PanelError
        variant="inline"
        className="py-0"
        title="No se pudo cargar la cronología del contrato"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  }

  const eventos = data ?? [];
  if (eventos.length === 0) {
    return (
      <p role="status" className="text-tf-meta text-muted-foreground">
        Sin eventos registrados desde la adjudicación.
      </p>
    );
  }

  return (
    <ol className="space-y-2 border-l border-border/60 pl-3">
      {eventos.map((evento, indice) => (
        <li key={`${evento.fecha}-${evento.tipo}-${indice}`} className="relative">
          <span
            aria-hidden="true"
            className="absolute -left-[1.03rem] top-1.5 h-1.5 w-1.5 rounded-full bg-muted-foreground/70 ring-2 ring-card"
          />
          <div className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
            <span className="tf-tnum text-tf-micro text-muted-foreground">
              {fechaCorta(evento.fecha)}
            </span>
            <span className="text-tf-micro font-medium">
              {TIPO_EVENTO_LABELS[evento.tipo] ?? evento.tipo}
            </span>
            {evento.importe_delta_eur != null && evento.importe_delta_eur !== 0 && (
              <span
                className={cn(
                  "tf-tnum text-tf-micro font-medium",
                  evento.importe_delta_eur > 0 ? "text-success" : "text-destructive",
                )}
              >
                {evento.importe_delta_eur > 0 ? "+" : ""}
                {formatCompactCurrency(evento.importe_delta_eur)}
              </span>
            )}
          </div>
          <p className="text-tf-micro text-muted-foreground">{evento.descripcion}</p>
        </li>
      ))}
    </ol>
  );
}
