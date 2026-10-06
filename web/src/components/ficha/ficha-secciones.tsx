"use client";

import * as React from "react";
import { ExternalLink } from "lucide-react";
import { PanelEmpty, SectionTitle } from "@/components/console/panel";
import { EventosTimeline } from "@/components/eventos-timeline";
import { ResolucionesBlock, useResoluciones } from "@/components/resoluciones-block";
import { ScoreDesglose } from "@/components/score-desglose";
import { AvisoPestanaNueva } from "@/components/ui/aviso-pestana-nueva";
import { fuenteLinkLabel } from "@/lib/fuentes";
import type { LicitacionDetail } from "@/lib/licitacion-detail";
import { cn } from "@/lib/utils";

/**
 * Secciones de la ficha que el inspector y la ficha completa pintan igual.
 * Cada una trae su título y sabe callarse cuando no tiene nada que decir.
 */

type Nivel = "h3" | "h4";

/**
 * De qué está hecha la puntuación. Las barras son las del Radar
 * (`ScoreDesglose`): mismas etiquetas y mismo orden de dimensiones en las dos
 * pantallas. Los avisos no se repiten aquí: ya van en la cabecera.
 */
export function FichaPuntuacion({ licitacion: l, as = "h3" }: { licitacion: LicitacionDetail; as?: Nivel }) {
  const id = React.useId();
  if (l.score == null) return null;
  return (
    <section aria-labelledby={id}>
      <SectionTitle as={as} id={id}>
        Desglose de la puntuación
      </SectionTitle>
      <ScoreDesglose desglose={l.score_desglose} />
    </section>
  );
}

/** Por encima de esto, el inspector recorta la descripción a cuatro líneas. */
const DESCRIPCION_LARGA = 320;

export function FichaDescripcion({
  licitacion: l,
  recortar = false,
  as = "h3",
}: {
  licitacion: LicitacionDetail;
  /** En el inspector: cuatro líneas y «Leer completa». */
  recortar?: boolean;
  as?: Nivel;
}) {
  const id = React.useId();
  const [abierta, setAbierta] = React.useState(false);
  if (!l.descripcion) return null;
  const larga = recortar && l.descripcion.length > DESCRIPCION_LARGA;
  return (
    <section aria-labelledby={id}>
      <SectionTitle as={as} id={id}>
        Descripción
      </SectionTitle>
      <p
        className={cn(
          "whitespace-pre-wrap text-tf-body leading-relaxed text-muted-foreground text-pretty",
          larga && !abierta && "line-clamp-4",
        )}
      >
        {l.descripcion}
      </p>
      {larga && (
        <button
          type="button"
          aria-expanded={abierta}
          onClick={() => setAbierta((valor) => !valor)}
          className="mt-1 rounded-sm text-tf-meta font-medium text-primary transition-colors hover:text-foreground"
        >
          {abierta ? "Mostrar menos" : "Leer completa"}
        </button>
      )}
    </section>
  );
}

/** El enlace al portal de origen, rotulado con el nombre de la fuente. */
export function FichaFuente({ licitacion: l, className }: { licitacion: LicitacionDetail; className?: string }) {
  if (!l.url) return null;
  return (
    <a
      href={l.url}
      target="_blank"
      rel="noopener noreferrer"
      // `flex w-fit` en vez de `inline-flex`: el margen de una caja en línea no
      // separa de lo que viene detrás.
      className={cn("flex w-fit items-center gap-1.5 text-tf-body font-medium", className)}
    >
      {fuenteLinkLabel(l.fuente, l.url)} <ExternalLink className="h-3 w-3" aria-hidden="true" />
      <AvisoPestanaNueva />
    </a>
  );
}

/**
 * Qué le ha pasado al expediente: modificaciones, prórrogas, adjudicación. Va
 * junto a los campos y no en su propia pestaña: es lo que dice si el importe o
 * la fecha límite que acabas de leer vienen de una modificación.
 * `EventosTimeline` trae su propio estado de carga, de error y de vacío.
 */
export function FichaEventos({ licitacionId, as = "h3" }: { licitacionId: string; as?: Nivel }) {
  const id = React.useId();
  return (
    <section aria-labelledby={id}>
      <SectionTitle as={as} id={id}>
        Eventos
      </SectionTitle>
      <EventosTimeline licitacionId={licitacionId} />
    </section>
  );
}

/** Resoluciones del TACRC, o el vacío que dice que no consta ninguna. */
export function FichaRecursos({ licitacionId, className }: { licitacionId: string; className?: string }) {
  const { data } = useResoluciones(licitacionId);
  const total = data?.items?.length ?? 0;
  if (total > 0) {
    return (
      <div className={cn("[&>*:first-child]:mt-0", className)}>
        <ResolucionesBlock licitacionId={licitacionId} />
      </div>
    );
  }
  return (
    <PanelEmpty
      size="sm"
      className={className}
      title="Sin recursos registrados"
      hint="No consta ninguna resolución del TACRC para este expediente."
    />
  );
}
