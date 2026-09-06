"use client";

import type { RadarTender } from "@/hooks/use-radar";
import { cn, formatCurrency, formatDate } from "@/lib/utils";
import { ExpectedCompetition } from "./radar-competencia-esperada";
import { Fact, SectionTitle } from "./radar-inspector-piezas";
import { DESGLOSE_LABELS, daysLeft, urgency } from "./radar-shared";

/**
 * Cuerpo del inspector: los seis datos del anuncio, el desglose del score, la
 * línea de tiempo y la competencia esperada. Es la única parte que hace scroll.
 *
 * Nada de esto se calcula aquí: el desglose viene del scoring y si no lo ha
 * devuelto se dice, en vez de pintar seis barras a cero — que se leería como
 * «puntúa cero en todo». La línea de tiempo pinta sólo los hitos con fecha: un
 * evento vacío se lee como «no ha pasado», que es una afirmación que el dato no
 * sostiene.
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
    <div className="min-h-0 flex-1 overflow-y-auto px-4.5 pt-4">
      <div className="mb-5 grid grid-cols-2 gap-px overflow-hidden rounded-[9px] border border-border/60 bg-border/60">
        <Fact label="Órgano" value={tender.organo_contratacion ?? "—"} />
        <Fact label="Importe" value={formatCurrency(tender.importe)} variant="mono" />
        <Fact
          label="Cierre"
          value={days != null ? `${days} días` : formatDate(tender.fecha_limite)}
          variant="mono"
          color={urg.color}
        />
        <Fact label="Tecnología" value={tender.tecnologia ?? tender.ml_tech_principal ?? "—"} />
        <Fact label="CPV" value={tender.cpv ?? "—"} variant="mono" />
        <Fact label="Ámbito" value={tender.ccaa ?? "—"} />
      </div>

      {/* El aside decía «ADR-014 · backend». Es la referencia interna de la
          decisión que prohíbe calcular analítica en el navegador: le dice al
          equipo dónde mirar y al usuario, nada. Lo que sí le importa es de
          dónde sale el número, y eso es lo que dice ahora. */}
      <SectionTitle
        aside={<span className="text-[10.5px] text-muted-foreground/70">calculado en servidor</span>}
      >
        Desglose de score
      </SectionTitle>
      <div className="mb-5.5 flex flex-col gap-[7px]">
        {desglose.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            El scoring todavía no ha devuelto desglose para esta licitación.
          </p>
        ) : (
          desglose.map(([key, value]) => (
            <div key={key} className="grid grid-cols-[88px_1fr_30px] items-center gap-2.5">
              <span className="text-[11.5px] text-muted-foreground">
                {DESGLOSE_LABELS[key] ?? key}
              </span>
              <span className="block h-[5px] overflow-hidden rounded-[3px] bg-muted-foreground/15">
                <span
                  className="block h-full w-full origin-left bg-linear-to-r from-primary/55 to-primary transition-transform duration-[420ms] ease-out"
                  style={{ transform: `scaleX(${Math.max(0, Math.min(1, value / 100))})` }}
                />
              </span>
              <span className="tf-tnum text-right font-mono text-[11px] font-medium">
                {Math.round(value)}
              </span>
            </div>
          ))
        )}
      </div>

      <SectionTitle>Línea de tiempo</SectionTitle>
      <div className="mb-5.5 flex flex-col">
        {events.map((event, index) => (
          <div key={event.label} className="grid grid-cols-[14px_1fr] items-start gap-2.5">
            <div className="flex h-full flex-col items-center">
              <span
                className={cn(
                  "mt-1 h-[7px] w-[7px] shrink-0 rounded-full",
                  index === 0 ? "bg-primary shadow-[0_0_0_3px_hsl(var(--primary)/0.14)]" : "bg-muted-foreground/35",
                )}
              />
              {index < events.length - 1 && (
                <span className="w-px flex-1 bg-muted-foreground/20" />
              )}
            </div>
            <div className="pb-3">
              <div className="text-xs font-medium leading-[1.3]">{event.label}</div>
              <div className="mt-0.5 font-mono text-[10.5px] leading-[1.3] text-muted-foreground">
                {formatDate(event.date)}
              </div>
            </div>
          </div>
        ))}
      </div>

      <ExpectedCompetition organo={tender.organo_contratacion} />
    </div>
  );
}
