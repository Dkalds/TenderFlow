"use client";

import { Fact, ROTULO_DATO } from "@/components/console/panel";
import { CodigoLegible } from "@/components/codigo-legible";
import type { LicitacionDetail } from "@/lib/licitacion-detail";
import { cn, formatDate } from "@/lib/utils";
import { hitosDelExpediente, type Hito } from "./ficha-fechas";

/**
 * Los campos publicados del expediente, en la rejilla de 1 px de la consola.
 *
 * El órgano, la provincia y la comunidad ya van bajo el título, y la fecha
 * límite en las cifras: aquí no se repiten.
 *
 * - `inspector`: con las fechas de publicación, inicio y fin.
 * - `completa`: sin ellas, porque la ficha completa las dibuja en su
 *   calendario; a cambio, la comunidad y la provincia en campos sueltos.
 */
export function FichaCampos({
  licitacion: l,
  variante,
  className,
}: {
  licitacion: LicitacionDetail;
  variante: "inspector" | "completa";
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border/60 bg-border/60",
        variante === "completa" && "lg:grid-cols-4",
        className,
      )}
    >
      <Fact
        label="Tipo de contrato"
        value={l.tipo_contrato ? <CodigoLegible familia="tipo_contrato" codigo={l.tipo_contrato} /> : null}
      />
      {/* F1.7 — etiqueta legible y definición desde `/meta/filters`. */}
      <Fact
        label="Procedimiento"
        value={l.procedimiento ? <CodigoLegible familia="procedimiento" codigo={l.procedimiento} /> : null}
      />
      <Fact
        label="Tramitación"
        value={l.tramitacion ? <CodigoLegible familia="tramitacion" codigo={l.tramitacion} /> : null}
      />
      <Fact label="CPV" value={l.cpv} variant="codigo" />
      <Fact label="Tecnología" value={l.tecnologia} />
      {variante === "inspector" ? (
        <>
          <Fact label="Publicación" value={formatDate(l.fecha_publicacion)} variant="cifra" />
          <Fact label="Inicio" value={formatDate(l.fecha_inicio)} variant="cifra" />
          <Fact label="Fin" value={formatDate(l.fecha_fin)} variant="cifra" />
        </>
      ) : (
        <>
          <Fact label="Comunidad autónoma" value={l.ccaa} />
          <Fact label="Provincia" value={l.provincia} />
          <Fact label="Publicación" value={formatDate(l.fecha_publicacion)} variant="cifra" />
        </>
      )}
    </div>
  );
}

/**
 * Clases estáticas del punto de cada hito: el JIT de Tailwind no ve una clase
 * compuesta en tiempo de ejecución. La fecha límite toma la banda de la rampa
 * de urgencia, que su texto («8 d para cierre») también dice.
 */
const PUNTO_LIMITE: Record<NonNullable<Hito["banda"]>, string> = {
  pasado: "bg-muted-foreground/60",
  critico: "bg-[hsl(var(--urgency-critical))]",
  alto: "bg-[hsl(var(--urgency-high))]",
  medio: "bg-[hsl(var(--urgency-medium))]",
  holgado: "bg-[hsl(var(--urgency-low))]",
};

const TEXTO_LIMITE: Record<NonNullable<Hito["banda"]>, string> = {
  pasado: "text-muted-foreground",
  critico: "text-[hsl(var(--urgency-critical))]",
  alto: "text-[hsl(var(--urgency-high))]",
  medio: "text-[hsl(var(--urgency-medium))]",
  holgado: "text-[hsl(var(--urgency-low))]",
};

function clasePunto(hito: Hito): string {
  if (hito.clave === "hoy") return "border-2 border-primary bg-card";
  if (hito.clave === "limite" && hito.banda) return PUNTO_LIMITE[hito.banda];
  return hito.pasado ? "bg-primary" : "bg-muted-foreground/40";
}

/**
 * Publicación, fecha límite, inicio y fin en una línea, con «hoy» en su sitio:
 * de un vistazo, si aún se puede presentar oferta y cuánto queda de contrato.
 * En móvil la línea se pone en vertical.
 */
export function FichaCalendario({ licitacion, className }: { licitacion: LicitacionDetail; className?: string }) {
  const hitos = hitosDelExpediente(licitacion);
  if (hitos.length === 0) return null;
  return (
    <ol
      aria-label="Calendario del expediente"
      className={cn(
        "flex flex-col gap-2.5 sm:grid sm:gap-0 sm:grid-cols-[repeat(var(--hitos),minmax(0,1fr))]",
        className,
      )}
      style={{ ["--hitos" as string]: String(hitos.length) }}
    >
      {hitos.map((hito, i) => {
        const siguiente = hitos[i + 1];
        // El tramo hasta el siguiente hito está recorrido si ese hito ya pasó.
        const recorrido = siguiente?.pasado ?? false;
        return (
          <li key={hito.clave} className="flex items-center gap-2.5 sm:flex-col sm:items-stretch sm:gap-1.5">
            <span aria-hidden="true" className="flex flex-none items-center sm:flex-1">
              <span className={cn("h-2.5 w-2.5 flex-none rounded-full", clasePunto(hito))} />
              {siguiente && (
                <span className={cn("hidden h-0.5 flex-1 sm:block", recorrido ? "bg-primary" : "bg-border")} />
              )}
            </span>
            <span className="flex min-w-0 flex-col sm:pr-2">
              <span className={ROTULO_DATO}>{hito.etiqueta}</span>
              <span className="tf-tnum text-tf-body font-medium">
                {formatDate(hito.fecha)}
                {hito.plazo && hito.banda && (
                  <span className={cn("ml-1.5 text-tf-meta", TEXTO_LIMITE[hito.banda])}>{hito.plazo}</span>
                )}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
