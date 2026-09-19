"use client";

/**
 * F1.7 — un código CODICE (procedimiento, tramitación, tipo de contrato) con
 * su etiqueta legible y el `?` del glosario.
 *
 * La etiqueta y la definición salen de `GET /meta/filters`, que comparte clave
 * de caché con la barra de ámbito: pintar cien filas no pide nada más que la
 * única consulta del catálogo.
 */

import { GlosarioHint } from "@/components/ui/glosario-hint";
import { useMetaFilters } from "@/hooks/use-meta-filters";
import { type FamiliaCodigo, glosarioDeCodigo, resolverCodigo } from "@/lib/procedimientos";
import { cn } from "@/lib/utils";

export function CodigoLegible({
  familia,
  codigo,
  className,
  conAyuda = true,
}: {
  familia: FamiliaCodigo;
  codigo: string | null | undefined;
  className?: string;
  /** Sin `?`: para celdas donde el botón de ayuda no cabe o ya está en la cabecera. */
  conAyuda?: boolean;
}) {
  const { data: meta } = useMetaFilters();
  const resuelto = resolverCodigo(meta, familia, codigo);
  if (!resuelto) return null;
  const entrada = conAyuda ? glosarioDeCodigo(familia, resuelto) : undefined;
  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      <span>{resuelto.etiqueta}</span>
      {!resuelto.catalogado && (
        <span className="text-[10px] font-normal text-muted-foreground">(código no catalogado)</span>
      )}
      {entrada && <GlosarioHint entrada={entrada} />}
    </span>
  );
}
