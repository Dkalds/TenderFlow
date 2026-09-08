"use client";

import * as React from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScoreDesglose } from "@/components/score-desglose";
import { cn } from "@/lib/utils";
import type { RadarTender } from "@/hooks/use-radar";
import { RadarAcciones } from "./radar-acciones";
import { RADAR_GRID, bandColor, daysLeft, shortEur, urgency } from "./radar-shared";

/**
 * Una señal del Radar: fila de la tabla a partir de `md`, ficha en columna por
 * debajo.
 *
 * **Es un solo árbol.** Los cuatro envoltorios de dentro agrupan la ficha móvil
 * y se disuelven con `md:contents`: a partir de `md` sus hijos caen directos en
 * la rejilla, en el mismo orden que rotula la cabecera. Es lo que permite que
 * ficha y fila no puedan divergir — una segunda lista `md:hidden` sí podría.
 */
export function RadarFila({
  tender,
  index,
  isActive,
  isFollowed,
  isNew,
  rowHeight,
  enTabla,
  conFicha,
  onSelect,
  onDismiss,
  onFollow,
  onOpenPursuit,
  onOpenFicha,
  afinidadOrigen,
}: {
  tender: RadarTender;
  index: number;
  isActive: boolean;
  isFollowed: boolean;
  isNew: boolean;
  rowHeight: number;
  /**
   * De dónde sale el portfolio con el que se calculó la afinidad (S2.4). Es
   * de la respuesta entera, no de la fila: el scorer lo resuelve una vez por
   * petición. Sin él el desglose calla, que es lo correcto contra un backend
   * que aún no lo mande.
   */
  afinidadOrigen?: string | null;
  /** A partir de `md` las acciones ocultas salen del orden de tabulación. */
  enTabla: boolean;
  conFicha: boolean;
  onSelect: (index: number) => void;
  onDismiss: (tender: RadarTender) => void;
  onFollow: (tender: RadarTender) => void;
  onOpenPursuit: (tender: RadarTender) => void;
  onOpenFicha: (index: number) => void;
}) {
  const days = daysLeft(tender.fecha_limite);
  const urg = urgency(days);
  const tech = tender.tecnologia ?? tender.ml_tech_principal ?? null;

  return (
    <div
      data-active={isActive}
      aria-current={isActive ? "true" : undefined}
      // El alto fijo de fila es de la tabla: en la ficha el título
      // ocupa dos líneas y recortarla a 44 px la dejaría sin nada.
      style={{ "--tf-radar-fila": `${rowHeight}px` } as React.CSSProperties}
      className={cn(
        "relative flex flex-col gap-2 border-b border-border/40 px-3 py-3 transition-colors duration-110 ease-out",
        "md:grid md:h-[var(--tf-radar-fila)] md:items-center md:py-0",
        RADAR_GRID,
        isActive ? "bg-primary/9" : "hover:bg-primary/5",
      )}
    >
      {/* Seleccionar la fila es un botón EN CAPA, hermano de las
          acciones y no su ancestro. Antes la fila entera era
          `role="button"` con cinco botones dentro: eso es
          `nested-interactive` —la regla que C7.1 saca primero de
          `disableRules`— y es también por lo que «Seguir» no
          registraba desde la fila.
          El contenido que sí actúa (la puntuación y las acciones)
          sube con `relative z-10`; el resto queda debajo, así que
          un clic en el título sigue seleccionando. */}
      <button
        type="button"
        data-slot="radar-fila-seleccion"
        aria-label={`Seleccionar ${tender.titulo}`}
        onClick={() => onSelect(index)}
        // Tabular movía el foco sin mover la selección, así que el
        // inspector, la banda lateral y los atajos globales seguían
        // hablando de otra fila. Foco y selección son la misma cosa:
        // lo que estás mirando es sobre lo que actúas.
        onFocus={() => onSelect(index)}
        onKeyDown={(event) => {
          // Espacio lo resuelve el click nativo del botón. Intro lo
          // resuelve la fila, con su propio `index`: el listener de
          // `window` trabaja sobre `active` y abría un pursuit
          // —escritura en backend y navegación— sobre la fila
          // seleccionada, no sobre la enfocada. `preventDefault`
          // evita además el click sintético que Intro dispararía.
          if (event.key !== "Enter") return;
          event.preventDefault();
          onSelect(index);
          onOpenPursuit(tender);
        }}
        className="focus-visible:ring-ring absolute inset-0 cursor-pointer focus-visible:ring-2 focus-visible:ring-inset focus-visible:outline-none"
      />

      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 left-0 w-0.5 transition-colors duration-110 ease-out"
        style={{ background: isActive ? bandColor(tender.band) : "transparent" }}
      />

      <div className="flex min-w-0 items-center gap-3 md:contents">
        {/* El score abre su propio desglose. Es un `Popover` y no
            un `title` nativo por dos razones: el `title` no se
            dispara con teclado y aquí el contenido no es una
            etiqueta sino datos. El `stopPropagation` evita que
            abrir la explicación cuente como seleccionar la fila. */}
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              data-slot="radar-score"
              onClick={(e) => e.stopPropagation()}
              aria-label={
                tender.score != null
                  ? `Ver de qué está hecha la puntuación ${Math.round(tender.score)}`
                  : "Este expediente no está puntuado"
              }
              className="focus-visible:ring-ring relative z-10 flex flex-none cursor-pointer flex-col items-start gap-0.5 rounded-sm focus-visible:ring-2 focus-visible:outline-none"
            >
              <span
                className="tf-tnum font-mono text-[15px] font-semibold leading-none"
                style={{ color: bandColor(tender.band) }}
              >
                {tender.score != null ? Math.round(tender.score) : "—"}
              </span>
              {/* "s/p" era un código que nadie fuera del equipo
                  podía descifrar, en mono de 8 px. */}
              <span className="text-muted-foreground font-mono text-[8px] font-medium uppercase leading-none tracking-[0.04em]">
                {tender.band ?? "sin puntuar"}
              </span>
            </button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-[300px]" onClick={(e) => e.stopPropagation()}>
            <p className="mb-2.5 text-[11.5px] font-semibold">Cómo se compone esta puntuación</p>
            <ScoreDesglose
              desglose={tender.desglose}
              riesgos={tender.risk_flags}
              explicacion={tender.explicacion}
              afinidadOrigen={afinidadOrigen}
            />
            <p className="text-muted-foreground mt-2.5 text-[10.5px] leading-relaxed">
              Ordena el Radar sobre el corpus abierto. No es una recomendación comercial: mide
              encaje con tu perfil, no probabilidad de ganar.
            </p>
          </PopoverContent>
        </Popover>

        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-[7px]">
            {isNew && (
              <span className="flex-none rounded border border-[hsl(var(--success)/0.3)] bg-[hsl(var(--success)/0.12)] px-1 py-0.5 font-mono text-[8px] font-semibold uppercase tracking-[0.06em] text-[hsl(var(--success))]">
                Nueva
              </span>
            )}
            {/* Dos líneas en móvil, una en la tabla. Un título del
                TED ronda los 120 caracteres y empieza por el
                preámbulo administrativo: cortarlo en una línea a
                375 px deja fuera el objeto del contrato, que es lo
                único por lo que se mira el Radar.
                `line-clamp-1` y no `truncate` para la tabla: son la
                misma utilidad en las dos anchuras, así que el orden
                en cascada lo decide el prefijo `md:` y no la
                ordenación interna de Tailwind entre dos familias
                distintas que escriben `display`. */}
            <span
              className={cn(
                "min-w-0 line-clamp-2 text-[13px] leading-[1.35] tracking-[-0.005em]",
                "md:line-clamp-1 md:leading-[1.3]",
                isActive ? "font-semibold text-foreground" : "font-medium",
              )}
            >
              {tender.titulo}
            </span>
          </div>
          {/* Flujo inline, no flex: `text-overflow` se ignora en un
              contenedor flex y la línea se cortaría a medias. */}
          <div className="mt-0.5 block truncate font-mono text-[10.5px] leading-[1.3] text-muted-foreground/80">
            {[tender.id_externo, tender.cpv ? `CPV ${tender.cpv}` : null, tender.ccaa]
              .filter(Boolean)
              .join(" · ")}
          </div>
        </div>
      </div>

      {/* Órgano y tecnología son las dos columnas que se subordinan
          en móvil: siguen ahí, en una línea secundaria bajo el
          título, en vez de competir con score, plazo e importe. */}
      <div className="flex min-w-0 items-center justify-between gap-2 md:contents">
        <span className="min-w-0 flex-1 truncate text-xs leading-[1.35] text-muted-foreground">
          {tender.organo_contratacion ?? "—"}
        </span>

        {tech ? (
          <span className="max-w-[46%] flex-none justify-self-start truncate rounded-[5px] border border-[hsl(var(--info)/0.26)] bg-[hsl(var(--info)/0.1)] px-1.5 py-1 text-[11px] font-medium text-[hsl(var(--info))] md:max-w-full">
            {tech}
          </span>
        ) : (
          <span className="flex-none text-[11px] text-muted-foreground/60">—</span>
        )}
      </div>

      <div className="flex items-center justify-between gap-3 md:contents">
        <span className="tf-tnum font-mono text-[13px] font-semibold md:text-right">
          {shortEur(tender.importe)}
        </span>

        <div className="flex flex-none flex-col items-end gap-1.5">
          <span
            className="tf-tnum font-mono text-xs font-semibold leading-none"
            style={{ color: urg.color }}
          >
            {days != null ? `${days} d` : "—"}
          </span>
          <span className="block h-0.5 w-14 overflow-hidden rounded-sm bg-muted-foreground/20">
            <span
              className="block h-full w-full origin-left transition-transform duration-[420ms] ease-out"
              style={{ background: urg.color, transform: `scaleX(${urg.ratio})` }}
            />
          </span>
        </div>
      </div>

      <RadarAcciones
        tender={tender}
        isActive={isActive}
        inerte={enTabla && !isActive}
        followed={isFollowed}
        conFicha={conFicha}
        onDismiss={() => onDismiss(tender)}
        onFollow={() => onFollow(tender)}
        onOpenPursuit={() => onOpenPursuit(tender)}
        onOpenFicha={() => onOpenFicha(index)}
      />
    </div>
  );
}
