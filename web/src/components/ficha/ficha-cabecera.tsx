"use client";

import * as React from "react";
import { ExternalLink, Link2, MessageSquareText } from "lucide-react";
import { toast } from "sonner";
import { CompararBoton } from "@/components/pliego/comparacion-bandeja";
import { ReportarDatoBoton } from "@/components/pliego/reportar-dato";
import { RecurridoBadge } from "@/components/resoluciones-block";
import { SeguirBoton } from "@/components/seguir-boton";
import { AvisoPestanaNueva } from "@/components/ui/aviso-pestana-nueva";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { GlosarioHint } from "@/components/ui/glosario-hint";
import { StatusBadge } from "@/components/ui/status-badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { fuenteLinkLabel } from "@/lib/fuentes";
import type { LicitacionDetail } from "@/lib/licitacion-detail";
import { riesgoLabel } from "@/lib/riesgos";
import { cn } from "@/lib/utils";

/**
 * La cabecera de la ficha de una licitación, en piezas: la comparten el
 * inspector de /detalle y la ficha completa, que las colocan distinto pero
 * tienen que decir lo mismo.
 */

/** Estado, aviso de recurrida y expediente. */
export function FichaEstado({ licitacion: l, className }: { licitacion: LicitacionDetail; className?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-wrap items-center gap-2", className)}>
      <StatusBadge value={l.estado} kind="estado" showIcon />
      {/* F1.8 — «Evaluación» no dice que ya no se puede presentar. */}
      <GlosarioHint termino={l.estado ?? undefined} />
      <RecurridoBadge licitacionId={l.id_externo} />
      <span className="truncate font-mono text-tf-micro text-muted-foreground">{l.id_externo}</span>
    </div>
  );
}

/**
 * Quién licita y dónde, justo bajo el título. Antes el órgano era uno más de
 * los doce campos de la rejilla, por debajo del pliegue del inspector.
 */
export function FichaOrgano({ licitacion: l, className }: { licitacion: LicitacionDetail; className?: string }) {
  const lugar = [l.provincia, l.ccaa].filter(Boolean).join(", ");
  if (!l.organo_contratacion && !lugar) return null;
  return (
    <p className={cn("flex flex-wrap items-baseline gap-x-1.5 text-tf-body text-muted-foreground", className)}>
      {l.organo_contratacion && <span className="font-medium text-foreground">{l.organo_contratacion}</span>}
      {l.organo_contratacion && lugar && <span aria-hidden="true">·</span>}
      {lugar && <span>{lugar}</span>}
    </p>
  );
}

/**
 * Los avisos del score, a la vista desde la cabecera. Aviso y no alarma: un
 * riesgo es algo que leer antes de decidir, no un fallo (el mismo tono que en
 * el desglose del Radar).
 */
export function FichaAvisos({ flags, className }: { flags: string[] | undefined; className?: string }) {
  if (!flags || flags.length === 0) return null;
  return (
    <ul aria-label="Avisos de la puntuación" className={cn("flex flex-wrap gap-1.5", className)}>
      {flags.map((flag) => (
        <li key={flag}>
          <Badge variant="warning" size="sm">
            {riesgoLabel(flag)}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

const CLASES_SEGUIR = {
  base: cn(buttonVariants({ variant: "outline", size: "sm" }), "tf-pressable flex-none"),
  activo: "border-primary/50 bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary",
  inactivo: "",
};

/**
 * Lo que se hace con la licitación: seguirla, compararla, compartirla,
 * preguntar a la IA y reportar un dato erróneo. Con `conFuente`, además, el
 * enlace al portal de origen como acción principal.
 */
export function FichaAcciones({
  licitacion: l,
  onPreguntar,
  conFuente = false,
  claseFuente,
  className,
}: {
  licitacion: LicitacionDetail;
  onPreguntar: () => void;
  conFuente?: boolean;
  /** Clases del enlace al portal (p. ej. esconderlo en móvil, donde va al pie). */
  claseFuente?: string;
  className?: string;
}) {
  const copiarEnlace = React.useCallback(async () => {
    const url = `${window.location.origin}/detalle?lic=${encodeURIComponent(l.id_externo)}`;
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Enlace copiado al portapapeles");
    } catch {
      toast.error("No se pudo copiar el enlace");
    }
  }, [l.id_externo]);

  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      {/* El control único de seguimiento (ADR-031 §C): el mismo de la estrella
          de la tabla, así que marcar aquí la enciende allí. */}
      <SeguirBoton
        targetType="licitacion"
        targetId={l.id_externo}
        icono="estrella"
        nombreAccesible="visible"
        clases={CLASES_SEGUIR}
      />
      <CompararBoton id={l.id_externo} titulo={l.titulo} />
      <Tooltip>
        <TooltipTrigger asChild>
          <Button type="button" variant="outline" size="sm" onClick={() => void copiarEnlace()}>
            <Link2 aria-hidden="true" />
            Copiar enlace
          </Button>
        </TooltipTrigger>
        <TooltipContent>Enlace directo a esta ficha</TooltipContent>
      </Tooltip>
      <Button type="button" variant="outline" size="sm" onClick={onPreguntar}>
        <MessageSquareText aria-hidden="true" />
        Preguntar a la IA
      </Button>
      <ReportarDatoBoton licitacionId={l.id_externo} />
      {conFuente && l.url && (
        <Button asChild size="sm" className={claseFuente}>
          <a href={l.url} target="_blank" rel="noopener noreferrer">
            {fuenteLinkLabel(l.fuente, l.url)}
            <ExternalLink aria-hidden="true" />
            <AvisoPestanaNueva />
          </a>
        </Button>
      )}
    </div>
  );
}
