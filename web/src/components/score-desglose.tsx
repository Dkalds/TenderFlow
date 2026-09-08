"use client";

import { EMPTY } from "@/lib/utils";
import { riesgoLabel } from "@/lib/riesgos";

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

/**
 * Contra qué se midió la afinidad (S2.4, `ScoringSignalsHealth.afinidad_origen`).
 *
 * La barra «Afinidad» dice cuánto encaja; esto dice **con qué**, que es lo que
 * cambia su significado. Desde S2.4 el portfolio puede salir de dos sitios: el
 * perfil personal de quien mira, o la capacidad declarada de su organización
 * (referencias y familias de `/equipo`). No es lo mismo «encaja con lo que tú
 * dijiste que haces» que «encaja con lo que ha hecho tu empresa», y quien lee
 * el desglose para decidir si puja merece saber cuál de las dos está viendo.
 *
 * `ninguno` no se calla ni se pinta como avería: es la explicación de por qué
 * la fila «Afinidad» puede no estar, y el camino para arreglarlo.
 */
const AFINIDAD_ORIGEN_TEXTO: Record<string, string> = {
  perfil: "Afinidad medida contra tu perfil personal.",
  organizacion: "Afinidad medida contra la capacidad declarada de tu organización.",
  ninguno: "Ni tu perfil ni tu organización declaran a qué os dedicáis: la afinidad no mide encaje.",
};

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
  /**
   * F1.3 — el mismo cálculo en castellano, generado en backend
   * (`ScoredOpportunity.explicacion`). Se pinta **encima** de las barras: son
   * la respuesta a «por qué debería mirar esta», y las barras a «de qué está
   * hecho el 82», que es la segunda pregunta y no la primera.
   *
   * No se deriva aquí ni se reescribe: el frontend no fabrica analítica
   * (ADR-014), y además así el texto es idéntico en la tarjeta, en el
   * inspector y en el PDF de F2.7.
   */
  explicacion?: string[];
  /**
   * S2.4 — `perfil | organizacion | ninguno`, tal cual lo emite
   * `ScoringSignalsHealth.afinidad_origen`. Es de la respuesta entera, no de
   * la fila: viaja en `signals`, no en `ScoredOpportunity`.
   *
   * Opcional a propósito: un valor desconocido (o ausente) no pinta nada en
   * vez de inventar una procedencia. El frontend no fabrica analítica
   * (ADR-014); aquí solo rotula lo que el backend ya declaró.
   */
  afinidadOrigen?: string | null;
}

export function ScoreDesglose({
  desglose,
  riesgos,
  explicacion,
  afinidadOrigen,
}: ScoreDesgloseProps) {
  const filas = desglose ? ordenar(desglose) : [];
  const frases = explicacion ?? [];
  const origenTexto = afinidadOrigen ? AFINIDAD_ORIGEN_TEXTO[afinidadOrigen] : undefined;

  if (filas.length === 0 && frases.length === 0) {
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
      {frases.length > 0 && (
        <ul
          className={
            "text-foreground/85 flex flex-col gap-1 text-[11.5px] leading-snug" +
            (filas.length > 0 ? " border-border/60 mb-1 border-b pb-2" : "")
          }
        >
          {frases.map((frase) => (
            <li key={frase}>{frase}</li>
          ))}
        </ul>
      )}

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

      {origenTexto && (
        // Bajo las barras y antes de los avisos: es una nota sobre una de las
        // dimensiones, no una dimensión más ni una alerta.
        <p data-slot="afinidad-origen" className="text-muted-foreground text-[10.5px] leading-snug">
          {origenTexto}
        </p>
      )}

      {riesgos && riesgos.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1.5">
          {riesgos.map((flag) => (
            <span
              key={flag}
              className="border-destructive/32 bg-destructive/12 text-destructive inline-flex h-[20px] items-center rounded-md border px-1.5 text-[10.5px] font-medium"
            >
              {riesgoLabel(flag)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
