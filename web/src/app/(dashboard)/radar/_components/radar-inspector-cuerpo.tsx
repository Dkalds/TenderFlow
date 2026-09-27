"use client";

import { CodigoLegible } from "@/components/codigo-legible";
import { Fact, SectionTitle } from "@/components/console/panel";
import { DESGLOSE_LABELS } from "@/components/score-desglose";
import { GlosarioHint } from "@/components/ui/glosario-hint";
import type { RadarTender } from "@/hooks/use-radar";
import { cn, formatCurrency, formatDate } from "@/lib/utils";
import { ExpectedCompetition } from "./radar-competencia-esperada";
import { daysLeft, urgency } from "./radar-shared";

/**
 * Cuerpo del inspector: los ocho datos del anuncio, el desglose del score, la
 * línea de tiempo y la competencia esperada. Es la única parte que hace scroll.
 *
 * Nada de esto se calcula aquí: el desglose viene del scoring y si no lo ha
 * devuelto se dice, en vez de pintar seis barras a cero — que se leería como
 * «puntúa cero en todo». La línea de tiempo pinta sólo los hitos con fecha: un
 * evento vacío se lee como «no ha pasado», que es una afirmación que el dato no
 * sostiene.
 *
 * Rótulos y datos son los primitivos de la consola (`Fact`, `SectionTitle`):
 * rótulo en frase a 11 px, la mono solo para el CPV. Las etiquetas del
 * desglose salen de `score-desglose.tsx`, las mismas que el popover de la fila
 * y el inspector de Detalle.
 */
export function InspectorCuerpo({ tender }: { tender: RadarTender }) {
  const days = daysLeft(tender.fecha_limite);
  const urg = urgency(days);
  const desglose = Object.entries(tender.desglose ?? {});

  const events = [
    { label: "Publicación", date: tender.fecha_publicacion },
    { label: "Cierre de ofertas", date: tender.fecha_limite },
  ].filter((event) => Boolean(event.date));

  return (
    // Región con foco propio (axe `scrollable-region-focusable`): el cuerpo es
    // solo lectura —datos, desglose, hitos—, así que sin `tabIndex` el teclado
    // no tenía forma de desplazar lo que no cabe en el inspector.
    <div
      role="region"
      aria-label="Detalle de la señal"
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- región con scroll sin controles: WCAG 2.1.1 exige que el teclado pueda desplazarla (axe scrollable-region-focusable)
      tabIndex={0}
      className="relative min-h-0 flex-1 overflow-y-auto px-4.5 pt-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
    >
      <div className="mb-5 grid grid-cols-2 gap-px overflow-hidden rounded-md border border-border/60 bg-border/60">
        <Fact label="Órgano" value={tender.organo_contratacion} />
        <Fact label="Importe" value={tender.importe != null ? formatCurrency(tender.importe) : null} variant="cifra" />
        <Fact
          label="Cierre"
          value={
            days != null ? (
              <span className={urg.texto}>{days} días</span>
            ) : tender.fecha_limite ? (
              formatDate(tender.fecha_limite)
            ) : null
          }
          variant="cifra"
        />
        <Fact label="Tecnología" value={tender.tecnologia ?? tender.ml_tech_principal} />
        <Fact label="CPV" value={tender.cpv} variant="codigo" />
        <Fact label="Comunidad" value={tender.ccaa} />
        {/* F1.7 — quien no vive en la Ley 9/2017 lee «Abierto» y no «1»; la
            etiqueta y la definición las sirve `/meta/filters`. */}
        <Fact
          label="Procedimiento"
          value={
            tender.procedimiento ? (
              <CodigoLegible familia="procedimiento" codigo={tender.procedimiento} />
            ) : null
          }
        />
        <Fact
          label="Tramitación"
          value={
            tender.tramitacion ? <CodigoLegible familia="tramitacion" codigo={tender.tramitacion} /> : null
          }
        />
      </div>

      {/* De dónde sale el número, dicho con la ayuda del glosario y no con
          «calculado en servidor»: lo que le importa a quien lee es qué mide la
          puntuación, no dónde se calcula. */}
      <SectionTitle as="h3" hint={<GlosarioHint termino="score" />}>
        Desglose de score
      </SectionTitle>
      <div className="mb-5.5 flex flex-col gap-[7px]">
        {desglose.length === 0 ? (
          <p className="text-tf-meta text-muted-foreground">
            Aún no hay desglose de la puntuación de esta licitación.
          </p>
        ) : (
          desglose.map(([key, value]) => (
            <div key={key} className="grid grid-cols-[96px_1fr_30px] items-center gap-2.5">
              <span className="text-tf-meta text-muted-foreground">{DESGLOSE_LABELS[key] ?? key}</span>
              {/* Sin transición: la barra se pinta ya en su valor. El inspector
                  se monta de nuevo por expediente, y una barra que se desliza
                  dice que el dato cambió. */}
              <span className="block h-[5px] overflow-hidden rounded-full bg-muted-foreground/15">
                <span
                  className="block h-full w-full origin-left bg-primary"
                  style={{ transform: `scaleX(${Math.max(0, Math.min(1, value / 100))})` }}
                />
              </span>
              <span className="tf-tnum text-right text-tf-micro font-medium">{Math.round(value)}</span>
            </div>
          ))
        )}
      </div>

      <SectionTitle as="h3">Línea de tiempo</SectionTitle>
      <div className="mb-5.5 flex flex-col">
        {events.map((event, index) => (
          <div key={event.label} className="grid grid-cols-[14px_1fr] items-start gap-2.5">
            <div className="flex h-full flex-col items-center">
              <span
                className={cn(
                  "mt-1 h-[7px] w-[7px] shrink-0 rounded-full",
                  index === 0 ? "bg-primary" : "bg-muted-foreground/35",
                )}
              />
              {index < events.length - 1 && <span className="w-px flex-1 bg-muted-foreground/20" />}
            </div>
            <div className="pb-3">
              <div className="text-tf-meta font-medium">{event.label}</div>
              <div className="tf-tnum mt-0.5 text-tf-micro text-muted-foreground">{formatDate(event.date)}</div>
            </div>
          </div>
        ))}
      </div>

      <ExpectedCompetition organo={tender.organo_contratacion} />
    </div>
  );
}
