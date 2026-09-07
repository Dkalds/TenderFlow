"use client";

import Link from "next/link";
import { AlertTriangle, X } from "lucide-react";
import type { RadarTender } from "@/hooks/use-radar";
import { riesgoLabel } from "@/lib/riesgos";
import { bandColor, bandColorAlpha, daysLeft } from "./radar-shared";

/**
 * Cabecera del inspector: banda, referencia, score, título y la línea que
 * resume por qué mirar esta señal.
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

  return (
    <div className="flex-none border-b border-border/60 px-4.5 pb-3.5 pt-4">
      <div className="mb-2.5 flex items-center gap-2">
        <span
          className="inline-flex h-[22px] items-center rounded-md border px-2 text-[10.5px] font-semibold tracking-[0.02em]"
          style={{
            borderColor: bandColorAlpha(band, 0.34),
            background: bandColorAlpha(band, 0.14),
            color: bandColor(band),
          }}
        >
          {band ?? "Sin puntuar"}
        </span>
        <span className="font-mono text-[11px] text-muted-foreground">{tender.id_externo}</span>
        <div className="flex-1" />
        <span className="tf-tnum font-mono text-[22px] font-semibold leading-none">
          {tender.score != null ? Math.round(tender.score) : "—"}
        </span>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar inspector"
            className="tf-pressable ml-1 grid h-6 w-6 place-items-center rounded-md border border-border/70 text-muted-foreground transition-colors hover:text-foreground"
          >
            <X className="h-3 w-3" />
          </button>
        )}
      </div>
      <h2 className="mb-2 font-display text-[15px] font-semibold leading-[1.35] tracking-[-0.01em] text-pretty">
        <Link href={`/detalle?lic=${encodeURIComponent(tender.id_externo)}`} className="hover:underline">
          {tender.titulo}
        </Link>
      </h2>
      {tender.risk_flags?.length ? (
        <ul className="flex flex-wrap gap-1.5">
          {tender.risk_flags.map((flag) => (
            <li
              key={flag}
              className="inline-flex items-center gap-1 rounded border border-[hsl(var(--warning)/0.35)] bg-[hsl(var(--warning)/0.12)] px-1.5 py-1 text-[10.5px] text-[hsl(var(--warning))]"
            >
              <AlertTriangle className="h-3 w-3" aria-hidden="true" />
              {riesgoLabel(flag)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[12.5px] leading-[1.55] text-muted-foreground text-pretty">
          {tender.estado ? `Estado: ${tender.estado}.` : "Sin estado informado."}{" "}
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
