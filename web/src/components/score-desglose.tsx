"use client";

import { EMPTY } from "@/lib/utils";

/**
 * De qué está hecho el score, en la pantalla donde se decide.
 *
 * El Radar ordena la bandeja entera por este número y hasta el 2026-08-30 no
 * había ninguna vía desde ahí para saber de qué está hecho: la fila abría con
 * el score coloreado por banda y debajo el código de banda en mono de 8 px. El
 * desglose **ya venía descargado** —`ScoredOpportunity.desglose`, en el mismo
 * payload que pinta la fila— y solo se mostraba en el inspector de `/detalle`,
 * que es otra pantalla y otro momento.
 *
 * En un producto que vende confianza en el dato, un número que ordena y no se
 * explica no se lee como preciso: se lee como opaco.
 *
 * Este componente es la pieza compartida para que las dos superficies no
 * puedan divergir en las etiquetas ni en el orden de las dimensiones.
 */

/**
 * Nombre legible de cada dimensión del score.
 *
 * Las claves son las que emite `services/analytics/scoring.py`. Una dimensión
 * nueva sin entrada aquí se pinta con su clave cruda —fea pero honesta— en vez
 * de desaparecer del desglose, que dejaría un total sin explicar.
 */
export const DESGLOSE_LABELS: Record<string, string> = {
  importe: "Importe",
  plazo: "Plazo",
  competencia: "Competencia",
  margen: "Margen esperado",
  afinidad: "Afinidad",
  senal_tecnica: "Señal técnica",
  riesgo: "Riesgo",
};

/** Orden estable: el del scoring, no el que devuelva `Object.entries`. */
const ORDEN = Object.keys(DESGLOSE_LABELS);

function ordenar(desglose: Record<string, number>): [string, number][] {
  return Object.entries(desglose).sort(([a], [b]) => {
    const ia = ORDEN.indexOf(a);
    const ib = ORDEN.indexOf(b);
    // Las dimensiones desconocidas van al final, en orden alfabético.
    if (ia === -1 && ib === -1) return a.localeCompare(b);
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });
}

export interface ScoreDesgloseProps {
  desglose: Record<string, number> | undefined;
  /** Banderas de riesgo que acompañan al score, si las hay. */
  riesgos?: string[];
}

export function ScoreDesglose({ desglose, riesgos }: ScoreDesgloseProps) {
  const filas = desglose ? ordenar(desglose) : [];

  if (filas.length === 0) {
    // "Sin desglose" y no una lista vacía: el hueco silencioso se lee como que
    // la pieza está rota, no como que este expediente no tiene detalle.
    return (
      <p className="text-muted-foreground text-[11.5px]">
        {EMPTY} Este expediente no trae desglose de puntuación.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-[7px]">
      {filas.map(([dim, valor]) => (
        <div key={dim} className="grid grid-cols-[96px_1fr_30px] items-center gap-2.5">
          <span className="text-muted-foreground text-[11.5px]">
            {DESGLOSE_LABELS[dim] ?? dim}
          </span>
          <span
            role="progressbar"
            aria-valuenow={Math.min(100, valor)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`Puntuación ${DESGLOSE_LABELS[dim] ?? dim}`}
            className="bg-muted-foreground/15 block h-[5px] overflow-hidden rounded-[3px]"
          >
            <span
              className="from-primary/55 to-primary block h-full w-full origin-left bg-linear-to-r transition-transform duration-[420ms] ease-out"
              style={{ transform: `scaleX(${Math.min(100, valor) / 100})` }}
            />
          </span>
          <span className="tf-tnum text-right font-mono text-[11px] font-medium">
            {valor.toFixed(1)}
          </span>
        </div>
      ))}

      {riesgos && riesgos.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1.5">
          {riesgos.map((flag) => (
            <span
              key={flag}
              className="border-destructive/32 bg-destructive/12 text-destructive inline-flex h-[20px] items-center rounded-md border px-1.5 text-[10.5px] font-medium"
            >
              {flag}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
