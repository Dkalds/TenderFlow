"use client";

/**
 * De dónde sale la fecha de fin de un contrato: publicada o calculada.
 *
 * Sólo el ~6% de los contratos trae `fecha_fin` de la fuente; el resto se
 * estima con `fecha_inicio + duración` (o, en último recurso, con la fecha de
 * adjudicación). El horizonte de renovaciones las pintaba todas igual, así que
 * una fecha inventada por aritmética se leía como una fecha oficial — y sobre
 * esa fecha se decide cuándo empezar a preparar la relicitación.
 *
 * `real` no lleva distintivo a propósito: lo excepcional es la estimación, y
 * marcar también lo normal convierte el badge en ruido.
 */
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const ETIQUETA: Record<string, { texto: string; explicacion: string }> = {
  estimada_inicio: {
    texto: "estimada",
    explicacion:
      "Calculada con la fecha de inicio y la duración del contrato; la fuente no publicó fecha de fin.",
  },
  estimada_adjudicacion: {
    texto: "estimada",
    explicacion:
      "Calculada con la fecha de adjudicación y la duración del contrato; no consta ni fecha de fin ni de inicio.",
  },
  desconocida: {
    texto: "sin fecha",
    explicacion: "La fuente no publica fecha de fin ni duración con la que calcularla.",
  },
};

export function FechaFinOrigenBadge({ origen }: { origen?: string | null }) {
  const etiqueta = origen ? ETIQUETA[origen] : undefined;
  if (!etiqueta) return null;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex h-[18px] flex-none items-center rounded-sm border border-border/70 bg-muted/60 px-1.5 text-[10px] font-medium text-muted-foreground">
          {etiqueta.texto}
        </span>
      </TooltipTrigger>
      <TooltipContent>{etiqueta.explicacion}</TooltipContent>
    </Tooltip>
  );
}
