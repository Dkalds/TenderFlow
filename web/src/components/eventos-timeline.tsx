"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatCurrency, formatDate } from "@/lib/utils";

interface EventoContrato {
  fecha: string | null;
  tipo: string;
  campo: string | null;
  valor_antes: string | null;
  valor_despues: string | null;
  importe_delta: number | null;
  detalle: string | null;
}

const TIPO_LABELS: Record<string, string> = {
  publicacion: "Publicación",
  adjudicacion: "Adjudicación",
  formalizacion: "Formalización",
  modificacion: "Modificación",
  prorroga: "Prórroga",
  anulacion: "Anulación",
  cambio_estado: "Cambio de estado",
  recurso: "Recurso",
};

const TIPO_VARIANTS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  publicacion: "outline",
  adjudicacion: "default",
  formalizacion: "default",
  modificacion: "secondary",
  prorroga: "secondary",
  anulacion: "destructive",
  cambio_estado: "outline",
  recurso: "destructive",
};

const TIPO_DOT: Record<string, string> = {
  publicacion: "bg-muted-foreground",
  adjudicacion: "bg-primary",
  formalizacion: "bg-primary",
  modificacion: "bg-amber-500",
  prorroga: "bg-amber-500",
  anulacion: "bg-destructive",
  cambio_estado: "bg-muted-foreground",
  recurso: "bg-destructive",
};

export function EventosTimeline({ licitacionId }: { licitacionId: string }) {
  const { data, isLoading, error } = useQuery<{ items: EventoContrato[] }>({
    queryKey: ["eventos", licitacionId],
    queryFn: () =>
      fetchWithAuth(`/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/eventos`),
    staleTime: 5 * 60 * 1000,
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
      <p className="text-sm text-muted-foreground">
        No se pudo cargar la línea de tiempo.
      </p>
    );
  }

  const items = data?.items ?? [];
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">Sin eventos registrados.</p>;
  }

  return (
    <ol className="relative space-y-4 border-l border-border pl-4">
      {items.map((ev, i) => (
        <li key={`${ev.fecha}-${ev.tipo}-${i}`} className="relative">
          <span
            className={cn(
              "absolute -left-[1.32rem] top-1.5 h-2.5 w-2.5 rounded-full ring-4 ring-background",
              TIPO_DOT[ev.tipo] ?? "bg-muted-foreground",
            )}
            aria-hidden
          />
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={TIPO_VARIANTS[ev.tipo] ?? "outline"} className="text-xs">
              {TIPO_LABELS[ev.tipo] ?? ev.tipo}
            </Badge>
            <span className="text-xs text-muted-foreground">{formatDate(ev.fecha)}</span>
            {ev.importe_delta != null && ev.importe_delta !== 0 && ev.tipo !== "adjudicacion" && (
              <span
                className={cn(
                  "text-xs font-medium",
                  ev.importe_delta > 0 ? "text-green-600" : "text-red-600",
                )}
              >
                {ev.importe_delta > 0 ? "+" : ""}
                {formatCurrency(ev.importe_delta)}
              </span>
            )}
            {ev.tipo === "adjudicacion" && ev.importe_delta != null && (
              <span className="text-xs font-medium">{formatCurrency(ev.importe_delta)}</span>
            )}
          </div>
          {ev.detalle && (
            <p className="mt-1 text-sm leading-snug text-foreground/90">{ev.detalle}</p>
          )}
          {ev.campo && ev.valor_antes != null && ev.valor_despues != null && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {ev.campo}: {ev.valor_antes} → {ev.valor_despues}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
