"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";
import { ExternalLink } from "lucide-react";

interface Resolucion {
  id: number;
  tribunal: string;
  numero_resolucion: string;
  numero_recurso: string | null;
  fecha: string | null;
  sentido: string | null;
  url_pdf: string | null;
  resumen: string | null;
}

const SENTIDO_LABELS: Record<string, string> = {
  estimado: "Estimado",
  desestimado: "Desestimado",
  inadmitido: "Inadmitido",
  desistimiento: "Desistimiento",
};

const SENTIDO_VARIANTS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  estimado: "destructive", // estimado = la adjudicación peligra
  desestimado: "secondary",
  inadmitido: "outline",
  desistimiento: "outline",
};

export function useResoluciones(licitacionId: string) {
  return useQuery<{ items: Resolucion[] }>({
    queryKey: ["resoluciones", licitacionId],
    queryFn: () =>
      fetchWithAuth(`/api/v1/resoluciones?licitacion_id=${encodeURIComponent(licitacionId)}`),
    staleTime: 5 * 60 * 1000,
  });
}

/** Bloque "Recursos" del detail panel: resoluciones TACRC vinculadas. */
export function ResolucionesBlock({ licitacionId }: { licitacionId: string }) {
  const { data } = useResoluciones(licitacionId);
  const items = data?.items ?? [];
  if (items.length === 0) return null;

  return (
    <div className="mt-6 space-y-3">
      <h3 className="text-sm font-medium text-muted-foreground">Recursos</h3>
      <ul className="space-y-3">
        {items.map((r) => (
          <li key={r.id} className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant={SENTIDO_VARIANTS[r.sentido ?? ""] ?? "outline"}
                className="text-xs"
              >
                {SENTIDO_LABELS[r.sentido ?? ""] ?? r.sentido ?? "Resolución"}
              </Badge>
              <span className="text-sm font-medium">
                {r.tribunal.toUpperCase()} {r.numero_resolucion}
              </span>
              {r.fecha && (
                <span className="text-xs text-muted-foreground">{formatDate(r.fecha)}</span>
              )}
            </div>
            {r.numero_recurso && (
              <p className="text-xs text-muted-foreground">Recurso nº {r.numero_recurso}</p>
            )}
            {r.url_pdf && (
              <a
                href={r.url_pdf}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
              >
                Ver resolución <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Badge "Recurrido" para la cabecera del detail panel. */
export function RecurridoBadge({ licitacionId }: { licitacionId: string }) {
  const { data } = useResoluciones(licitacionId);
  if (!data?.items?.length) return null;
  return <Badge variant="destructive">Recurrido</Badge>;
}
