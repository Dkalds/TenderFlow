"use client";

import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScoreDesglose } from "@/components/score-desglose";
import { cn } from "@/lib/utils";
import type { RadarTender } from "@/hooks/use-radar";
import { RadarAcciones } from "./radar-acciones";
import {
  RADAR_GRID,
  claseFondoBanda,
  claseTextoBanda,
  daysLeft,
  shortEur,
  urgency,
} from "./radar-shared";

/**
 * Una señal del Radar: fila de la tabla a partir de `lg`, ficha en columna por
 * debajo.
 *
 * **Es un solo árbol.** Los cuatro envoltorios de dentro agrupan la ficha móvil
 * y se disuelven con `lg:contents`: a partir de `lg` sus hijos caen directos en
 * la rejilla, en el mismo orden que rotula la cabecera. Es lo que permite que
 * ficha y fila no puedan divergir — una segunda lista `lg:hidden` sí podría.
 *
 * **La selección no se anima.** J/K es la acción más repetida del Radar: la
 * fila que entra y la que sale cambian de fondo al instante, y la banda lateral
 * también. Solo el hover funde al entrar (la transición existe mientras dura el
 * hover), y el pulsado del botón en capa tiñe la fila en el mismo frame.
 */
export function RadarFila({
  tender,
  index,
  isActive,
  isNew,
  rowHeight,
  enTabla,
  conFicha,
  onSelect,
  onDismiss,
  onFollowed,
  onOpenPursuit,
  onOpenFicha,
  onExplicacion,
  afinidadOrigen,
}: {
  tender: RadarTender;
  index: number;
  isActive: boolean;
  isNew: boolean;
  rowHeight: number;
  /**
   * De dónde sale el portfolio con el que se calculó la afinidad (S2.4). Es
   * de la respuesta entera, no de la fila: el scorer lo resuelve una vez por
   * petición. Sin él el desglose calla, que es lo correcto contra un backend
   * que aún no lo mande.
   */
  afinidadOrigen?: string | null;
  /** A partir de `lg` las acciones ocultas salen del orden de tabulación. */
  enTabla: boolean;
  conFicha: boolean;
  onSelect: (index: number) => void;
  onDismiss: (tender: RadarTender) => void;
  /** Tras alternar «Seguir» (lo hace `SeguirBoton`), con el estado nuevo. */
  onFollowed: (tender: RadarTender, ahoraSigue: boolean) => void;
  onOpenPursuit: (tender: RadarTender) => void;
  onOpenFicha: (index: number) => void;
  /** F1.3 — se abrió «cómo se compone esta puntuación» de esta fila. */
  onExplicacion?: (tender: RadarTender) => void;
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
        "relative flex flex-col gap-2 border-b border-border/40 px-3 py-3 md:px-3.5",
        "lg:grid lg:h-[var(--tf-radar-fila)] lg:items-center lg:py-0",
        RADAR_GRID,
        // `/9` y no `/10` en la fila activa: es el tinte que mide
        // `contraste-tokens.test.ts` con las cifras de banda encima.
        isActive
          ? "bg-primary/9"
          : cn(
              "hover:bg-primary/5 hover:transition-colors hover:duration-110",
              // Pulsado: el tinte de la fila activa en el mismo frame, sin el
              // fundido del hover. Solo el botón en capa, no «Seguir» ni
              // «Descartar»: `:active` sube a los ancestros.
              "has-[[data-slot=radar-fila-seleccion]:active]:bg-primary/9 has-[[data-slot=radar-fila-seleccion]:active]:duration-0",
            ),
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
        className={cn(
          "pointer-events-none absolute inset-y-0 left-0 w-0.5",
          isActive ? claseFondoBanda(tender.band) : "bg-transparent",
        )}
      />

      <div className="flex min-w-0 items-center gap-3 lg:contents">
        {/* El score abre su propio desglose. Es un `Popover` y no
            un `title` nativo por dos razones: el `title` no se
            dispara con teclado y aquí el contenido no es una
            etiqueta sino datos. El `stopPropagation` evita que
            abrir la explicación cuente como seleccionar la fila. */}
        <Popover onOpenChange={(abierto) => abierto && onExplicacion?.(tender)}>
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
                className={cn("tf-tnum text-tf-lede font-semibold leading-none", claseTextoBanda(tender.band))}
              >
                {tender.score != null ? Math.round(tender.score) : "—"}
              </span>
              {/* La banda en frase y a 11 px, como el chip del inspector. Fue
                  «s/p» y luego un rótulo en versal de 8 px: un código que nadie
                  fuera del equipo podía leer. Con score y sin banda no se
                  inventa una: sin score, se dice. */}
              <span className="text-tf-micro font-medium leading-none text-muted-foreground">
                {tender.score == null ? "Sin puntuar" : tender.band || null}
              </span>
            </button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-[300px]" onClick={(e) => e.stopPropagation()}>
            <p className="mb-2.5 text-tf-meta font-semibold">Cómo se compone esta puntuación</p>
            <ScoreDesglose
              desglose={tender.desglose}
              riesgos={tender.risk_flags}
              explicacion={tender.explicacion}
              afinidadOrigen={afinidadOrigen}
            />
            <p className="mt-2.5 text-tf-micro text-muted-foreground">
              Ordena las licitaciones abiertas del Radar. No es una recomendación comercial: mide
              encaje con tu perfil, no probabilidad de ganar.
            </p>
          </PopoverContent>
        </Popover>

        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1.5">
            {isNew && (
              <Badge variant="success" size="sm" className="flex-none">
                Nueva
              </Badge>
            )}
            {/* Dos líneas en móvil, una en la tabla. Un título del
                TED ronda los 120 caracteres y empieza por el
                preámbulo administrativo: cortarlo en una línea a
                375 px deja fuera el objeto del contrato, que es lo
                único por lo que se mira el Radar.
                `line-clamp-1` y no `truncate` para la tabla: son la
                misma utilidad en las dos anchuras, así que el orden
                en cascada lo decide el prefijo `lg:` y no la
                ordenación interna de Tailwind entre dos familias
                distintas que escriben `display`. */}
            <span
              className={cn(
                "min-w-0 line-clamp-2 text-tf-body lg:line-clamp-1",
                isActive ? "font-semibold text-foreground" : "font-medium",
              )}
            >
              {tender.titulo}
            </span>
          </div>
          {/* Flujo inline, no flex: `text-overflow` se ignora en un
              contenedor flex y la línea se cortaría a medias. La mono solo
              para los códigos (expediente y CPV); la comunidad es una palabra. */}
          <div className="mt-0.5 block truncate text-tf-micro text-muted-foreground">
            <span className="font-mono">
              {[tender.id_externo, tender.cpv ? `CPV ${tender.cpv}` : null].filter(Boolean).join(" · ")}
            </span>
            {tender.ccaa ? <> · {tender.ccaa}</> : null}
            {/* Desde `xl` la tecnología no tiene columna (el inspector anclado
                se come el ancho, ver `RADAR_GRID`): va aquí, en texto. */}
            {tech ? <span className="hidden xl:inline"> · {tech}</span> : null}
          </div>
        </div>
      </div>

      {/* Órgano y tecnología son las dos columnas que se subordinan
          en móvil: siguen ahí, en una línea secundaria bajo el
          título, en vez de competir con score, plazo e importe. */}
      <div className="flex min-w-0 items-center justify-between gap-2 lg:contents">
        <span className="min-w-0 flex-1 truncate text-tf-meta text-muted-foreground">
          {tender.organo_contratacion ?? "—"}
        </span>

        {/* `xl:hidden`: desde `xl` la rejilla no tiene esta columna y la
            tecnología va en la línea del título. */}
        {tech ? (
          <Badge
            variant="info"
            size="sm"
            className="block max-w-[46%] flex-none justify-self-start truncate leading-5 lg:max-w-full xl:hidden"
          >
            {tech}
          </Badge>
        ) : (
          <span className="flex-none text-tf-micro text-muted-foreground xl:hidden">—</span>
        )}
      </div>

      <div className="flex items-center justify-between gap-3 lg:contents">
        <span className="tf-tnum text-tf-body font-semibold lg:text-right">{shortEur(tender.importe)}</span>

        <div className="flex flex-none flex-col items-end gap-1.5">
          <span className={cn("tf-tnum text-tf-meta font-semibold leading-none", urg.texto)}>
            {days != null ? `${days} d` : "—"}
          </span>
          {/* La mecha se pinta ya en su valor: una transición entre dos
              expedientes diría que uno de ellos cambió. */}
          <span className="block h-0.5 w-14 overflow-hidden rounded-sm bg-muted-foreground/20">
            <span className={cn("block h-full", urg.fondo, urg.ancho)} />
          </span>
        </div>
      </div>

      <RadarAcciones
        tender={tender}
        isActive={isActive}
        inerte={enTabla && !isActive}
        conFicha={conFicha}
        onDismiss={() => onDismiss(tender)}
        onFollowed={(ahoraSigue) => onFollowed(tender, ahoraSigue)}
        onOpenPursuit={() => onOpenPursuit(tender)}
        onOpenFicha={() => onOpenFicha(index)}
      />
    </div>
  );
}
