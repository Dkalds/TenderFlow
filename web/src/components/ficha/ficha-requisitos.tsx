"use client";

import * as React from "react";
import { PanelEmpty, PanelError, SectionTitle } from "@/components/console/panel";
import { CondicionesOficialesBloque } from "@/components/pliego/condiciones-oficiales";
import { Skeleton } from "@/components/ui/skeleton";
import { useCondicionesOficiales, type CondicionesOficiales } from "@/hooks/use-condiciones-oficiales";
import { getSeriesTextClass } from "@/lib/chart-colors";
import type { LicitacionDetail } from "@/lib/licitacion-detail";
import { cn, formatCurrency, formatDate, formatPercent } from "@/lib/utils";

/**
 * Qué piden para presentarse: lotes, criterios, garantías y solvencia tal como
 * los publica el anuncio (`GET /condiciones-oficiales`, v148).
 *
 * Antes vivían dentro de la ficha de los pliegos, debajo de su extracción, y
 * solo se veían abriendo la pestaña Pliegos. Son lo que decide si te presentas,
 * así que tienen sección propia en el inspector y en la ficha completa; la
 * ficha de los pliegos se queda con lo extraído del documento.
 */

type Nivel = "h3" | "h4";

function FichaLotes({ licitacion: l, as }: { licitacion: LicitacionDetail; as: Nivel }) {
  const id = React.useId();
  const lotes = l.lotes ?? [];
  return (
    <section aria-labelledby={id}>
      <SectionTitle as={as} id={id}>
        Lotes
      </SectionTitle>
      {lotes.length === 0 ? (
        <p className="text-tf-body text-muted-foreground">Un solo contrato, sin división en lotes.</p>
      ) : (
        <ul className="divide-y divide-divider overflow-hidden rounded-xl border border-divider">
          {lotes.map((lote) => (
            <li key={lote.numero} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-3 py-2">
              <span className="font-mono text-tf-micro text-muted-foreground">Lote {lote.numero}</span>
              <span className="min-w-0 flex-[1_1_240px] text-tf-body">{lote.titulo ?? "Sin título publicado"}</span>
              {lote.importe != null && (
                <span className="tf-tnum text-tf-meta font-semibold">{formatCurrency(lote.importe)}</span>
              )}
              {lote.fecha_limite && (
                <span className="tf-tnum text-tf-meta text-muted-foreground">
                  Límite {formatDate(lote.fecha_limite)}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function FichaRequisitos({ licitacion: l, as = "h3" }: { licitacion: LicitacionDetail; as?: Nivel }) {
  const { data, isLoading, error, refetch } = useCondicionesOficiales(l.id_externo);
  const hayCondiciones = (data?.ambitos?.length ?? 0) > 0;
  return (
    <div className="flex flex-col gap-5">
      <FichaLotes licitacion={l} as={as} />
      {isLoading ? (
        <div className="space-y-2" aria-hidden="true">
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : error != null ? (
        <PanelError
          variant="inline"
          title="No se pudo leer la publicación oficial"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : hayCondiciones && data ? (
        <CondicionesOficialesBloque datos={data} licitacionId={l.id_externo} />
      ) : (
        <PanelEmpty
          size="sm"
          title="El anuncio no publica criterios, garantías ni solvencia"
          hint="Pueden estar en los pliegos: su ficha se extrae en la sección Pliegos."
        />
      )}
    </div>
  );
}

/**
 * Los criterios raíz del expediente que traen su peso sobre 100. Sin ninguno
 * así no hay reparto que dibujar: un peso en una escala que nadie publicó no
 * se convierte a porcentaje aquí (lo explica `condiciones-oficiales.tsx`).
 */
export function criteriosConPeso(datos: CondicionesOficiales | undefined) {
  const ambitos = datos?.ambitos ?? [];
  const ambito = ambitos.find((a) => a.lote_numero == null) ?? ambitos[0];
  return (ambito?.criterios ?? []).filter(
    (c): c is typeof c & { peso_pct: number } => c.padre_orden == null && c.peso_pct != null,
  );
}

/**
 * «Cómo se adjudica»: el reparto de los criterios en una barra, para el
 * inspector. Es un resumen de `FichaRequisitos`, no otra fuente: comparte su
 * consulta, así que no cuesta una petición más. Calla mientras carga, si falla
 * o si no hay pesos: el detalle completo y su error están en Requisitos.
 */
export function FichaComoSeAdjudica({ licitacionId, className }: { licitacionId: string; className?: string }) {
  const id = React.useId();
  const { data } = useCondicionesOficiales(licitacionId);
  const criterios = criteriosConPeso(data);
  if (criterios.length === 0) return null;
  // La barra es un SVG con anchos en atributos y no `div`s con estilo en
  // línea: los pesos son valores calculados y cada estilo en línea aleja
  // quitar `'unsafe-inline'` de la CSP (`scripts/check_inline_styles.py`).
  const total = criterios.reduce((suma, c) => suma + c.peso_pct, 0);
  const tramos = criterios.map((criterio, i) => ({
    orden: criterio.orden,
    x: (criterios.slice(0, i).reduce((suma, c) => suma + c.peso_pct, 0) / total) * 100,
    ancho: (criterio.peso_pct / total) * 100,
  }));
  return (
    <section aria-labelledby={id} className={cn("rounded-xl border border-divider px-3.5 py-3", className)}>
      <SectionTitle as="h3" id={id}>
        Cómo se adjudica
      </SectionTitle>
      <div aria-hidden="true" className="mb-2.5 h-2 overflow-hidden rounded-full">
        <svg viewBox="0 0 100 2" preserveAspectRatio="none" className="block h-full w-full">
          {tramos.map((tramo, i) => (
            <rect
              key={tramo.orden}
              x={tramo.x}
              y={0}
              // Medio punto de hueco entre tramos, salvo tras el último.
              width={Math.max(tramo.ancho - (i < tramos.length - 1 ? 0.5 : 0), 0)}
              height={2}
              fill="currentColor"
              className={getSeriesTextClass(i)}
            />
          ))}
        </svg>
      </div>
      <ul className="flex flex-col gap-1">
        {criterios.map((criterio, i) => (
          <li key={criterio.orden} className="flex items-baseline gap-2 text-tf-body">
            <span
              aria-hidden="true"
              className={cn("h-2 w-2 flex-none translate-y-[-1px] rounded-sm bg-current", getSeriesTextClass(i))}
            />
            <span className="min-w-0 flex-1">
              {criterio.descripcion ?? "Criterio sin descripción"}
              {criterio.nota && <span className="text-muted-foreground"> · {criterio.nota}</span>}
            </span>
            <span className="tf-tnum font-semibold">
              {formatPercent(criterio.peso_pct, Number.isInteger(criterio.peso_pct) ? 0 : 1)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
