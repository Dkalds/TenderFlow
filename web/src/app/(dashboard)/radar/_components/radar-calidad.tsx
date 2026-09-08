"use client";

/**
 * ¿Lo que el Radar pone arriba es lo que el equipo gana? (S3.2)
 *
 * `GET /pursuits/metrics` publica `radar_quality` desde el PR #274 y
 * `components/pursuits/radar-quality.tsx` sabía pintarlo, pero su único
 * consumidor era su propio test: la consola que promete priorizar bien no
 * enseñaba en ninguna parte si lo estaba haciendo.
 *
 * Aquí no se calcula nada. La precisión, el denominador, el umbral y la
 * ventana llegan resueltos del backend, y la regla de ADR-014 —sin denominador
 * suficiente no se pinta un porcentaje— ya vive dentro de `RadarQualityNota` /
 * `RadarQualityResumen`. Esta franja sólo decide **dónde** se dice y **qué
 * banda** encabeza: la Caliente, que es la que justifica el orden de la lista.
 *
 * Sin ninguna banda sellada no hay franja: un hueco es mejor que una frase
 * que no informa.
 */

import * as React from "react";
import { ChevronDown } from "lucide-react";
import { RadarQualityNota, RadarQualityResumen } from "@/components/pursuits/radar-quality";
import { usePursuitMetrics } from "@/hooks/use-pursuits";
import { cn } from "@/lib/utils";

export function RadarCalidad() {
  const { data } = usePursuitMetrics();
  const [abierto, setAbierto] = React.useState(false);

  const calidad = data?.radar_quality ?? null;
  const bandas = calidad?.bandas ?? [];
  if (!calidad || bandas.length === 0) return null;

  // Presencia, no cálculo: `RadarQualityNota` devuelve `null` si esa banda no
  // tiene oportunidades, y la franja necesita saberlo para poner en su lugar la
  // frase que sí se sostiene.
  const hayCaliente = bandas.some((banda) => banda.banda === "Caliente");

  return (
    <div className="flex-none border-b border-border/60 bg-card/40 px-3 py-1.5 md:px-3.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        {hayCaliente ? (
          <RadarQualityNota
            calidad={calidad}
            banda="Caliente"
            className="min-w-0 flex-1 text-[11px] leading-relaxed text-muted-foreground"
          />
        ) : (
          <p className="min-w-0 flex-1 text-[11px] leading-relaxed text-muted-foreground">
            Ninguna oportunidad abierta desde la banda Caliente ha llegado todavía a un cierre con
            veredicto.
          </p>
        )}
        <button
          type="button"
          onClick={() => setAbierto((previo) => !previo)}
          aria-expanded={abierto}
          aria-controls="radar-calidad-bandas"
          className="tf-pressable inline-flex h-6 flex-none items-center gap-1 rounded-md border border-transparent px-1.5 text-[11px] font-medium text-muted-foreground transition-colors duration-150 ease-out hover:text-foreground"
        >
          {abierto ? "Ocultar bandas" : "Ver todas las bandas"}
          <ChevronDown
            className={cn("h-3 w-3 transition-transform duration-150 ease-out", abierto && "rotate-180")}
            aria-hidden="true"
          />
        </button>
      </div>
      <div id="radar-calidad-bandas" hidden={!abierto}>
        <RadarQualityResumen calidad={calidad} className="mt-2 max-w-[520px]" />
      </div>
    </div>
  );
}
