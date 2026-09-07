"use client";

import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { TableCell } from "@/components/ui/table";
import { FechaFinOrigenBadge } from "@/components/pursuits/fecha-fin-origen-badge";
import { formatCurrency, truncate } from "@/lib/utils";
import type { RenovacionRow } from "../../_hooks/use-horizonte";

/** Semáforo del plazo: los mismos cortes de urgencia que usa el resto del producto. */
export function diasBadgeVariant(dias: number | null): "destructive" | "secondary" | "outline" {
  if (dias == null) return "outline";
  if (dias <= 30) return "destructive";
  if (dias <= 90) return "secondary";
  return "outline";
}

/**
 * Las ocho celdas de un contrato que vence.
 *
 * Es el `itemContent` de la tabla virtualizada, así que se pinta y se descarta
 * al vuelo mientras se hace scroll: nada de estado propio aquí dentro.
 *
 * `maxScore` es el máximo del top servido y llega como prop porque la columna
 * «Oportunidad» es **relativa**: sin el mismo denominador para todas las filas,
 * cada una diría un número que no se puede comparar con el de al lado
 * (ADR-014). El `stopPropagation` de los dos controles evita que pulsarlos
 * dispare además la navegación al detalle que lleva la fila entera.
 */
export function CeldasRenovacion({
  fila,
  maxScore,
  onAnticipar,
}: {
  fila: RenovacionRow;
  maxScore: number;
  onAnticipar: (licitacionId: string) => void;
}) {
  const relativo = maxScore > 0 ? Math.round((fila._score / maxScore) * 100) : 0;

  return (
    <>
      <TableCell className="whitespace-nowrap">
        <div className="flex flex-col gap-1">
          <span className="flex items-center gap-1.5 text-sm">
            {fila.fecha_fin_efectiva ?? "—"}
            {/* Sólo el ~6% de estas fechas las publica la fuente;
                el resto sale de la duración del contrato. */}
            <FechaFinOrigenBadge origen={fila.fecha_fin_origen} />
          </span>
          <Badge variant={diasBadgeVariant(fila.dias_restantes)} className="w-fit">
            {fila.dias_restantes != null ? `${fila.dias_restantes} días` : "—"}
          </Badge>
          {fila.prorroga_meses != null && (
            <span className="text-[10.5px] leading-tight text-muted-foreground">
              +{fila.prorroga_meses} meses de prórroga
              {fila.fecha_fin_con_prorroga ? ` → ${fila.fecha_fin_con_prorroga}` : ""}
            </span>
          )}
        </div>
      </TableCell>
      <TableCell className="max-w-[320px]">
        <div className="flex items-start gap-1.5">
          <span className="text-sm leading-snug">{truncate(fila.titulo ?? fila.licitacion_id, 90)}</span>
          {fila.url && (
            <a
              href={fila.url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground"
              aria-label="Abrir anuncio original"
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
        </div>
      </TableCell>
      <TableCell className="max-w-[220px]">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-sm">{fila.empresa ?? "—"}</span>
          {fila.es_ute ? <Badge variant="outline">UTE</Badge> : null}
        </div>
      </TableCell>
      <TableCell className="max-w-[220px] truncate text-sm text-muted-foreground">
        {fila.organo_contratacion ?? "—"}
      </TableCell>
      <TableCell className="text-right text-sm font-medium whitespace-nowrap">
        {fila.importe_adjudicado != null ? formatCurrency(fila.importe_adjudicado) : "—"}
      </TableCell>
      <TableCell className="text-right whitespace-nowrap">
        {fila.riesgo_cambio != null ? (
          <Badge
            variant={
              fila.riesgo_cambio >= 0.6 ? "destructive" : fila.riesgo_cambio >= 0.35 ? "secondary" : "outline"
            }
            title={`Modelo de retención v${fila.retencion_model_version ?? "?"}`}
          >
            {(fila.riesgo_cambio * 100).toFixed(0)}%
          </Badge>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell className="text-right whitespace-nowrap">
        {fila._score > 0 ? (
          <Badge
            variant={relativo >= 66 ? "default" : relativo >= 33 ? "secondary" : "outline"}
            title="Riesgo × importe × urgencia (relativo al máximo del top servido)"
          >
            {relativo}
          </Badge>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell className="text-right whitespace-nowrap">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onAnticipar(fila.licitacion_id);
          }}
          className="tf-pressable h-6 rounded-md border border-primary/30 bg-primary/8 px-2 text-[11px] font-medium text-primary"
        >
          Anticipar
        </button>
      </TableCell>
    </>
  );
}
