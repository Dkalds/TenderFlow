"use client";

import Link from "next/link";
import { TriangleAlert, X } from "lucide-react";
import { ChipBanda, esBandaConocida } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { GlosarioHint } from "@/components/ui/glosario-hint";
import type { RadarTender } from "@/hooks/use-radar";
import { estadoLabel } from "@/lib/estados";
import { riesgoLabel } from "@/lib/riesgos";
import { daysLeft } from "./radar-shared";

/**
 * Cabecera del inspector: banda, referencia, score, título y la línea que
 * resume por qué mirar esta señal.
 *
 * La banda es el chip único de la consola (`ChipBanda`, sobre `--score-*`), el
 * mismo que el inspector de Detalle: antes cada inspector la pintaba a su
 * manera, y este con un `style` en línea. Sin score se dice «Sin puntuar»; con
 * score y una banda que no es de las cuatro no se pinta chip, en vez de
 * inventar una. El score va a 20 px en sans, como la cifra de un KPI.
 *
 * Los avisos de riesgo desplazan a esa línea y no se suman a ella: si el
 * scoring marcó algo (plazo imposible, criterio subjetivo…), eso es lo que hay
 * que leer primero, y repetir debajo el estado y los días lo enterraría.
 * Cuando no hay avisos se dice el estado y el plazo, cada uno declarando su
 * ausencia si la fuente no lo publica.
 *
 * `onClose` sólo llega en el modo Sheet (md–xl): anclado no hay nada que
 * cerrar, así que el botón no existe en vez de existir sin efecto.
 */
export function InspectorCabecera({ tender, onClose }: { tender: RadarTender; onClose?: () => void }) {
  const days = daysLeft(tender.fecha_limite);
  const band = tender.band ?? null;
  const sinPuntuar = tender.score == null;

  return (
    <div className="flex-none border-b border-border/60 px-4.5 pb-3.5 pt-4">
      <div className="mb-2.5 flex items-center gap-2">
        {(sinPuntuar || esBandaConocida(band)) && <ChipBanda banda={sinPuntuar ? null : band} size="md" />}
        <span className="font-mono text-tf-micro text-muted-foreground">{tender.id_externo}</span>
        <div className="flex-1" />
        <span className="tf-tnum text-tf-title font-semibold leading-none">
          {sinPuntuar ? "—" : Math.round(tender.score!)}
        </span>
        {onClose && (
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            onClick={onClose}
            aria-label="Cerrar inspector"
            className="ml-1"
          >
            <X aria-hidden="true" />
          </Button>
        )}
      </div>
      <h2 className="mb-2 font-display text-tf-lede font-semibold text-pretty">
        <Link href={`/detalle?lic=${encodeURIComponent(tender.id_externo)}`} className="hover:underline">
          {tender.titulo}
        </Link>
      </h2>
      {tender.risk_flags?.length ? (
        <ul className="flex flex-wrap gap-1.5">
          {tender.risk_flags.map((flag) => (
            <li key={flag}>
              <Badge variant="warning" size="sm">
                <TriangleAlert aria-hidden="true" />
                {riesgoLabel(flag)}
              </Badge>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-tf-body text-muted-foreground text-pretty">
          {tender.estado ? (
            <>
              {/* F1.8 — la etiqueta y no el código crudo (`PUB`), con su ayuda. */}
              Estado: {estadoLabel(tender.estado)} <GlosarioHint termino={tender.estado} />.
            </>
          ) : (
            "Sin estado informado."
          )}{" "}
          {days != null
            ? days >= 0
              ? `Quedan ${days} días para el cierre.`
              : `El plazo cerró hace ${Math.abs(days)} días.`
            : "Sin fecha límite publicada."}
        </p>
      )}
    </div>
  );
}
