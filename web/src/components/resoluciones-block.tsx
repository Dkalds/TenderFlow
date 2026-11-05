"use client";

import { useQuery } from "@tanstack/react-query";
import type * as React from "react";
import { apiGet } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { PanelEmpty, PanelError, SectionTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { cn, formatDate } from "@/lib/utils";
import { ExternalLink } from "lucide-react";
import { AvisoPestanaNueva } from "@/components/ui/aviso-pestana-nueva";
import { resolucionesKeys } from "@/lib/query-keys";

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
  return useQuery({
    queryKey: resolucionesKeys.byLicitacion(licitacionId),
    queryFn: ({ signal }) =>
      apiGet("/api/v1/resoluciones", { params: { query: { licitacion_id: licitacionId } }, signal }),
    staleTime: 5 * 60 * 1000,
    // El fallo lo dicen el bloque y la chapa, cada uno en su sitio: sin toast.
    meta: META_ERROR_EN_LINEA,
  });
}

/**
 * Bloque "Recursos" del detail panel: resoluciones TACRC vinculadas.
 *
 * Carga, fallo y vacío se distinguen. Hasta 2026-11 los tres devolvían `null`,
 * y un `/resoluciones` caído se leía igual que «sin recursos»: justo lo que no
 * puede parecer una licitación recurrida. `conTitulo={false}` cuando el
 * contenedor ya rotula la sección.
 */
export function ResolucionesBlock({ licitacionId, conTitulo = true }: { licitacionId: string; conTitulo?: boolean }) {
  const { data, isPending, error, refetch } = useResoluciones(licitacionId);
  const items = data?.items ?? [];

  let cuerpo: React.ReactNode;
  if (isPending) {
    cuerpo = (
      <div className="space-y-2" aria-hidden="true">
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-4 w-1/3" />
      </div>
    );
  } else if (error) {
    cuerpo = (
      <PanelError
        variant="inline"
        className="py-0"
        title="No se pudo comprobar si hay recursos"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  } else if (items.length === 0) {
    cuerpo = (
      <PanelEmpty
        size="sm"
        className="py-0"
        title="Sin recursos registrados"
        hint="No consta ninguna resolución del TACRC para este expediente."
      />
    );
  } else {
    cuerpo = <ListaResoluciones items={items} />;
  }

  return (
    <div className={cn("space-y-3", conTitulo && "mt-6")} aria-busy={isPending || undefined}>
      {conTitulo && <SectionTitle as="h3">Recursos</SectionTitle>}
      {cuerpo}
    </div>
  );
}

function ListaResoluciones({ items }: { items: Schemas["ResolucionOut"][] }) {
  return (
    <ul className="space-y-3">
      {items.map((r) => (
        <li key={r.id} className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={SENTIDO_VARIANTS[r.sentido ?? ""] ?? "outline"} size="sm">
              {SENTIDO_LABELS[r.sentido ?? ""] ?? r.sentido ?? "Resolución"}
            </Badge>
            {/* El tribunal es una sigla (TACRC): la versal es la suya, no un estilo. */}
            <span className="text-tf-body font-medium">
              {[r.tribunal?.toUpperCase(), r.numero_resolucion].filter(Boolean).join(" ") || "Resolución"}
            </span>
            {r.fecha && <span className="tf-tnum text-tf-meta text-muted-foreground">{formatDate(r.fecha)}</span>}
          </div>
          {r.numero_recurso && <p className="text-tf-meta text-muted-foreground">Recurso nº {r.numero_recurso}</p>}
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
  );
}

/**
 * Badge "Recurrido" para la cabecera del detail panel. Mientras carga y sin
 * recursos no pinta nada: la cabecera no reserva sitio para una chapa que lo
 * normal es que no salga. Si la consulta falla lo dice, porque callarse ahí
 * es afirmar «no recurrida» sin saberlo.
 */
export function RecurridoBadge({ licitacionId }: { licitacionId: string }) {
  const { data, error } = useResoluciones(licitacionId);
  if (data?.items?.length) return <Badge variant="destructive">Recurrido</Badge>;
  if (error) return <Badge variant="outline">Recursos sin comprobar</Badge>;
  return null;
}
