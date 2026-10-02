"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { SectionTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";
import { ExternalLink } from "lucide-react";
import { AvisoPestanaNueva } from "@/components/ui/aviso-pestana-nueva";
import { resolucionesKeys } from "@/lib/query-keys";

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
    queryKey: resolucionesKeys.byLicitacion(licitacionId),
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
      <SectionTitle as="h3">Recursos</SectionTitle>
      <ul className="space-y-3">
        {items.map((r) => (
          <li key={r.id} className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={SENTIDO_VARIANTS[r.sentido ?? ""] ?? "outline"} size="sm">
                {SENTIDO_LABELS[r.sentido ?? ""] ?? r.sentido ?? "Resolución"}
              </Badge>
              {/* El tribunal es una sigla (TACRC): la versal es la suya, no un estilo. */}
              <span className="text-tf-body font-medium">
                {r.tribunal.toUpperCase()} {r.numero_resolucion}
              </span>
              {r.fecha && <span className="tf-tnum text-tf-meta text-muted-foreground">{formatDate(r.fecha)}</span>}
            </div>
            {r.numero_recurso && (
              <p className="text-tf-meta text-muted-foreground">Recurso nº {r.numero_recurso}</p>
            )}
            {r.url_pdf && (
              <a
                href={r.url_pdf}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-tf-meta text-primary hover:underline"
              >
                Ver resolución <ExternalLink className="h-3 w-3" aria-hidden="true" />
                <AvisoPestanaNueva />
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
