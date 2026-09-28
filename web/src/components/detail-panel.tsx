"use client";

import * as React from "react";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { LicitacionAI } from "@/components/licitacion-ai";
import { DocumentosBlock } from "@/components/documentos-block";
import { TecnologiasBlock } from "@/components/tecnologias-block";
import { EventosTimeline } from "@/components/eventos-timeline";
import { PrediccionBajaBlock } from "@/components/prediccion-baja";
import { RecurridoBadge, ResolucionesBlock } from "@/components/resoluciones-block";
import { ROTULO_DATO, SectionTitle } from "@/components/console/panel";
import { cn, EMPTY, formatCurrency, formatDate } from "@/lib/utils";
import { fuenteLinkLabel } from "@/lib/fuentes";
import { ExternalLink, Link2, MessageSquareText } from "lucide-react";
import { toast } from "sonner";
import { riesgoLabel } from "@/lib/riesgos";

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
  /** Fuente de ingesta (`placsp`, `ted`, `pscp`…): rotula `url`. Ver `lib/fuentes`. */
  fuente: string | null;
  tecnologia: string | null;
  tipo_contrato: string | null;
  /** F1.7 — código CODICE crudo; la etiqueta la pone `CodigoLegible`. */
  procedimiento?: string | null;
  tramitacion?: string | null;
  provincia: string | null;
  fecha_limite: string | null;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  descripcion: string | null;
  score?: number;
  /** Banda del scoring (`Caliente|Atractiva|Tibia|Descarte`), si ya llegó. */
  band?: string | null;
  score_desglose?: Record<string, number>;
  risk_flags?: string[];
}

interface DetailPanelProps {
  licitacion: LicitacionDetail;
  onClose: () => void;
  className?: string;
}

/** Labels presentacionales para las keys del desglose de scoring.
 *  Cualquier key no mapeada muestra la key raw (no rompe si la API añade dimensiones).
 */
const DESGLOSE_LABELS: Record<string, string> = {
  importe: "Importe",
  plazo: "Plazo",
  competencia: "Competencia",
  margen: "Margen esperado",
  afinidad: "Afinidad",
  senal_tecnica: "Señal técnica",
  riesgo: "Riesgo",
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <dt className={ROTULO_DATO}>{label}</dt>
      <dd className="text-tf-body">{children ?? <span className="text-muted-foreground">{EMPTY}</span>}</dd>
    </div>
  );
}

export function DetailPanel({ licitacion: l, onClose, className }: DetailPanelProps) {
  // Bump para activar el tab "Preguntar" del asistente IA desde la cabecera.
  const [askSignal, setAskSignal] = React.useState(0);

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
      <SheetContent side="right" className={cn("w-full overflow-y-auto sm:max-w-lg", className)}>
        <SheetHeader className="mb-6">
          <SheetTitle className="font-display text-tf-lede font-semibold text-pretty">
            {l.titulo ?? l.id_externo}
          </SheetTitle>
          <SheetDescription className="font-mono text-tf-meta">{l.id_externo}</SheetDescription>
        </SheetHeader>

        {/* Estado + importe */}
        <div className="mb-6 flex flex-wrap items-center gap-3">
          {/* El mismo chip de estado que el inspector de Detalle. */}
          {l.estado && <StatusBadge value={l.estado} kind="estado" />}
          <RecurridoBadge licitacionId={l.id_externo} />
          {l.importe != null && (
            <span className="tf-tnum text-tf-title font-semibold leading-none">{formatCurrency(l.importe)}</span>
          )}
          <Button variant="outline" size="sm" onClick={handleCopyLink}>
            <Link2 aria-hidden="true" />
            Copiar enlace
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setAskSignal((k) => k + 1);
              document.getElementById("licitacion-ai")?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
          >
            <MessageSquareText aria-hidden="true" />
            Preguntar a la IA
          </Button>
        </div>

        {/* Asistente IA contextualizado: resumen + chat sobre esta licitación */}
        <LicitacionAI idExterno={l.id_externo} askSignal={askSignal} />

        {/* Score section */}
        {l.score != null && (
          <div className="mb-6 space-y-2">
            <SectionTitle as="h3">Puntuación</SectionTitle>
            <div className="flex items-center gap-3">
              <div
                role="progressbar"
                aria-valuenow={Math.min(100, l.score)}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label="Puntuación"
                className="bg-muted h-2 flex-1 overflow-hidden rounded-full"
              >
                <div className="bg-primary h-full rounded-full" style={{ width: `${Math.min(100, l.score)}%` }} />
              </div>
              <span className="tf-tnum text-tf-body font-medium">{l.score.toFixed(1)}</span>
            </div>
            {l.score_desglose && (
              <div className="space-y-1 pl-1">
                {Object.entries(l.score_desglose).map(([dim, val]) => (
                  <div key={dim} className="flex items-center gap-2 text-tf-meta">
                    <span className="text-muted-foreground w-28 truncate">{DESGLOSE_LABELS[dim] ?? dim}</span>
                    <div
                      role="progressbar"
                      aria-valuenow={Math.min(100, val)}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-label={`Puntuación ${dim}`}
                      className="bg-muted h-1.5 flex-1 overflow-hidden rounded-full"
                    >
                      <div className="bg-primary/60 h-full rounded-full" style={{ width: `${Math.min(100, val)}%` }} />
                    </div>
                    <span className="tf-tnum w-8 text-right">{val.toFixed(1)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Risk flags */}
        {l.risk_flags && l.risk_flags.length > 0 && (
          <div className="mb-6 space-y-2">
            <SectionTitle as="h3">Alertas</SectionTitle>
            <div className="flex flex-wrap gap-1.5">
              {l.risk_flags.map((flag) => (
                <Badge key={flag} variant="destructive" size="sm">
                  {riesgoLabel(flag)}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Details grid */}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-4">
          <Field label="Órgano de contratación">{l.organo_contratacion}</Field>
          <Field label="CCAA">{l.ccaa}</Field>
          <Field label="Provincia">{l.provincia}</Field>
          <Field label="CPV">{l.cpv ? <span className="font-mono">{l.cpv}</span> : null}</Field>
          <Field label="Tipo de contrato">{l.tipo_contrato}</Field>
          <Field label="Tecnología">{l.tecnologia}</Field>
          <Field label="Fecha publicación">{formatDate(l.fecha_publicacion)}</Field>
          <Field label="Fecha límite">{formatDate(l.fecha_limite)}</Field>
          <Field label="Fecha inicio">{formatDate(l.fecha_inicio)}</Field>
          <Field label="Fecha fin">{formatDate(l.fecha_fin)}</Field>
        </dl>

        <TecnologiasBlock licitacionId={l.id_externo} />

        {/* Description */}
        {l.descripcion && (
          <div className="mt-6 space-y-1">
            <SectionTitle as="h3">Descripción</SectionTitle>
            <p className="text-tf-body whitespace-pre-wrap">{l.descripcion}</p>
          </div>
        )}

        {/* Eventos de contrato */}
        <div className="mt-6 space-y-3">
          <SectionTitle as="h3">Cronología</SectionTitle>
          <EventosTimeline licitacionId={l.id_externo} />
        </div>

        {/* Predicción de baja (Fase 6) */}
        <PrediccionBajaBlock licitacionId={l.id_externo} />

        {/* Resoluciones de recursos (TACRC) */}
        <ResolucionesBlock licitacionId={l.id_externo} />

        {/* Documentos (pliegos) parseados */}
        <DocumentosBlock licitacionId={l.id_externo} />

        {/* External link */}
        {l.url && (
          <a
            href={l.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary mt-6 inline-flex items-center gap-1.5 text-tf-body hover:underline"
          >
            {fuenteLinkLabel(l.fuente, l.url)} <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          </a>
        )}
      </SheetContent>
    </Sheet>
  );
}

export type { LicitacionDetail, DetailPanelProps };
