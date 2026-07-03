"use client";

import * as React from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EventosTimeline } from "@/components/eventos-timeline";
import { PrediccionBajaBlock } from "@/components/prediccion-baja";
import { RecurridoBadge, ResolucionesBlock } from "@/components/resoluciones-block";
import { cn, formatCurrency, formatDate } from "@/lib/utils";
import { ExternalLink, Link2 } from "lucide-react";
import { toast } from "sonner";

interface LicitacionDetail {
  id_externo: string;
  titulo: string | null;
  organo_contratacion: string | null;
  importe: number | null;
  estado: string | null;
  fecha_publicacion: string | null;
  ccaa: string | null;
  cpv: string | null;
  url: string | null;
  tecnologia: string | null;
  tipo_contrato: string | null;
  provincia: string | null;
  fecha_limite: string | null;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  descripcion: string | null;
  score?: number;
  score_desglose?: Record<string, number>;
  risk_flags?: string[];
}

interface DetailPanelProps {
  licitacion: LicitacionDetail;
  onClose: () => void;
  className?: string;
}

const ESTADO_VARIANTS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  "Adjudicada": "default",
  "Resuelta": "default",
  "En plazo": "secondary",
  "Evaluación": "secondary",
  "Anulada": "destructive",
  "Desierta": "destructive",
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children ?? <span className="text-muted-foreground">-</span>}</dd>
    </div>
  );
}

export function DetailPanel({ licitacion: l, onClose, className }: DetailPanelProps) {
  const handleCopyLink = React.useCallback(async () => {
    const url = `${window.location.origin}/detalle?lic=${encodeURIComponent(l.id_externo)}`;
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Enlace copiado al portapapeles");
    } catch {
      toast.error("No se pudo copiar el enlace");
    }
  }, [l.id_externo]);

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className={cn("w-full sm:max-w-lg overflow-y-auto", className)}>
        <SheetHeader className="mb-6">
          <SheetTitle className="text-base leading-snug">{l.titulo ?? l.id_externo}</SheetTitle>
          <SheetDescription>{l.id_externo}</SheetDescription>
        </SheetHeader>

        {/* Estado + importe */}
        <div className="mb-6 flex items-center gap-3 flex-wrap">
          {l.estado && (
            <Badge variant={ESTADO_VARIANTS[l.estado] ?? "outline"}>{l.estado}</Badge>
          )}
          <RecurridoBadge licitacionId={l.id_externo} />
          {l.importe != null && (
            <span className="text-lg font-semibold">{formatCurrency(l.importe)}</span>
          )}
          <Button
            variant="outline"
            size="sm"
            className="ml-auto gap-1.5"
            onClick={handleCopyLink}
          >
            <Link2 className="h-3.5 w-3.5" />
            Copiar enlace
          </Button>
        </div>

        {/* Score section */}
        {l.score != null && (
          <div className="mb-6 space-y-2">
            <h3 className="text-sm font-medium">Puntuación</h3>
              <div className="flex items-center gap-3">
                <div
                  role="progressbar"
                  aria-valuenow={Math.min(100, l.score)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label="Puntuación"
                  className="h-2 flex-1 rounded-full bg-muted overflow-hidden"
                >
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{ width: `${Math.min(100, l.score)}%` }}
                />
              </div>
              <span className="text-sm font-medium">{l.score.toFixed(1)}</span>
            </div>
            {l.score_desglose && (
              <div className="space-y-1 pl-1">
                {Object.entries(l.score_desglose).map(([dim, val]) => (
                  <div key={dim} className="flex items-center gap-2 text-xs">
                    <span className="w-28 truncate text-muted-foreground">{dim}</span>
                    <div
                      role="progressbar"
                      aria-valuenow={Math.min(100, val)}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-label={`Puntuación ${dim}`}
                      className="h-1.5 flex-1 rounded-full bg-muted overflow-hidden"
                    >
                      <div
                        className="h-full rounded-full bg-primary/60"
                        style={{ width: `${Math.min(100, val)}%` }}
                      />
                    </div>
                    <span className="w-8 text-right">{val.toFixed(1)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Risk flags */}
        {l.risk_flags && l.risk_flags.length > 0 && (
          <div className="mb-6 space-y-2">
            <h3 className="text-sm font-medium">Alertas</h3>
            <div className="flex flex-wrap gap-1.5">
              {l.risk_flags.map((flag) => (
                <Badge key={flag} variant="destructive" className="text-xs">{flag}</Badge>
              ))}
            </div>
          </div>
        )}

        {/* Details grid */}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-4">
          <Field label="Órgano de contratación">{l.organo_contratacion}</Field>
          <Field label="CCAA">{l.ccaa}</Field>
          <Field label="Provincia">{l.provincia}</Field>
          <Field label="CPV">{l.cpv}</Field>
          <Field label="Tipo de contrato">{l.tipo_contrato}</Field>
          <Field label="Tecnología">{l.tecnologia}</Field>
          <Field label="Fecha publicación">{formatDate(l.fecha_publicacion)}</Field>
          <Field label="Fecha límite">{formatDate(l.fecha_limite)}</Field>
          <Field label="Fecha inicio">{formatDate(l.fecha_inicio)}</Field>
          <Field label="Fecha fin">{formatDate(l.fecha_fin)}</Field>
        </dl>

        {/* Description */}
        {l.descripcion && (
          <div className="mt-6 space-y-1">
            <h3 className="text-sm font-medium text-muted-foreground">Descripción</h3>
            <p className="text-sm whitespace-pre-wrap">{l.descripcion}</p>
          </div>
        )}

        {/* Eventos de contrato */}
        <div className="mt-6 space-y-3">
          <h3 className="text-sm font-medium text-muted-foreground">Línea de tiempo</h3>
          <EventosTimeline licitacionId={l.id_externo} />
        </div>

        {/* Predicción de baja (Fase 6) */}
        <PrediccionBajaBlock licitacionId={l.id_externo} />

        {/* Resoluciones de recursos (TACRC) */}
        <ResolucionesBlock licitacionId={l.id_externo} />

        {/* External link */}
        {l.url && (
          <a
            href={l.url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-6 inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
          >
            Ver en PLACSP <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
      </SheetContent>
    </Sheet>
  );
}

export type { LicitacionDetail, DetailPanelProps };
