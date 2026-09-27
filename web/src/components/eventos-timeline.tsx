"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { PanelEmpty, PanelError } from "@/components/console/panel";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatCurrency, formatDate } from "@/lib/utils";
import { eventosKeys } from "@/lib/query-keys";

interface EventoContrato {
  fecha: string | null;
  tipo: string;
  campo: string | null;
  valor_antes: string | null;
  valor_despues: string | null;
  importe_delta: number | null;
  detalle: string | null;
}

/**
 * El vocabulario de `contrato_eventos.tipo`, exportado porque lo comparten las
 * dos pantallas que leen esa tabla: esta cronología de la ficha de licitación
 * y la del contrato en Oportunidades › Cartera. Dos mapas para una sola
 * columna de la API acaban dando dos nombres al mismo hecho.
 */
export const TIPO_EVENTO_LABELS: Record<string, string> = {
  publicacion: "Publicación",
  adjudicacion: "Adjudicación",
  formalizacion: "Formalización",
  modificacion: "Modificación",
  prorroga: "Prórroga",
  anulacion: "Anulación",
  cambio_estado: "Cambio de estado",
  recurso: "Recurso",
};

/** Un tono por familia de hecho: el mismo en el chip y en el punto. */
const TIPO_VARIANTS: Record<string, NonNullable<BadgeProps["variant"]>> = {
  publicacion: "neutral",
  adjudicacion: "info",
  formalizacion: "info",
  modificacion: "warning",
  prorroga: "warning",
  anulacion: "destructive",
  cambio_estado: "neutral",
  recurso: "destructive",
};

const TIPO_DOT: Record<string, string> = {
  publicacion: "bg-muted-foreground",
  adjudicacion: "bg-info",
  formalizacion: "bg-info",
  modificacion: "bg-warning",
  prorroga: "bg-warning",
  anulacion: "bg-destructive",
  cambio_estado: "bg-muted-foreground",
  recurso: "bg-destructive",
};

export function EventosTimeline({ licitacionId }: { licitacionId: string }) {
  const { data, isLoading, error, refetch } = useQuery<{ items: EventoContrato[] }>({
    queryKey: eventosKeys.byLicitacion(licitacionId),
    queryFn: () =>
      fetchWithAuth(`/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/eventos`),
    staleTime: 5 * 60 * 1000,
    // El fallo se pinta aquí mismo (`PanelError`): sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-5 w-3/4" />
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-5 w-3/4" />
      </div>
    );
  }

  if (error) {
    return (
      <PanelError
        variant="inline"
        className="py-0"
        title="No se pudo cargar la cronología"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  }

  const items = data?.items ?? [];
  if (items.length === 0) {
    return <PanelEmpty size="sm" className="py-0 text-left" hint="Sin eventos registrados." />;
  }

  return (
    <ol className="relative space-y-4 border-l border-border pl-4">
      {items.map((ev, i) => (
        <li key={`${ev.fecha}-${ev.tipo}-${i}`} className="relative">
          <span
            className={cn(
              "absolute -left-[1.32rem] top-1.5 h-2.5 w-2.5 rounded-full ring-4 ring-card",
              TIPO_DOT[ev.tipo] ?? "bg-muted-foreground",
            )}
            aria-hidden="true"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={TIPO_VARIANTS[ev.tipo] ?? "neutral"} size="sm">
              {TIPO_EVENTO_LABELS[ev.tipo] ?? ev.tipo}
            </Badge>
            <span className="tf-tnum text-tf-meta text-muted-foreground">{formatDate(ev.fecha)}</span>
            {ev.importe_delta != null && ev.importe_delta !== 0 && ev.tipo !== "adjudicacion" && (
              <span
                className={cn(
                  "tf-tnum text-tf-meta font-medium",
                  ev.importe_delta > 0 ? "text-success" : "text-destructive",
                )}
              >
                {ev.importe_delta > 0 ? "+" : ""}
                {formatCurrency(ev.importe_delta)}
              </span>
            )}
            {ev.tipo === "adjudicacion" && ev.importe_delta != null && (
              <span className="tf-tnum text-tf-meta font-medium">{formatCurrency(ev.importe_delta)}</span>
            )}
          </div>
          {ev.detalle && (
            <p className="mt-1 text-tf-body leading-snug text-foreground/90">{ev.detalle}</p>
          )}
          {ev.campo && ev.valor_antes != null && ev.valor_despues != null && (
            <p className="mt-0.5 text-tf-meta text-muted-foreground">
              {ev.campo}: {ev.valor_antes} → {ev.valor_despues}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
