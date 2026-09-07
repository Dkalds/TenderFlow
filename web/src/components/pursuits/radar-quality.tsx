import type { PursuitMetrics } from "@/hooks/use-pursuits";

/**
 * Calidad del Radar: ¿lo que puso arriba es lo que el equipo ganó?
 *
 * El backend sella la banda con la que se abrió cada oportunidad desde la
 * revisión `v93` y hasta 2026-09 nadie la leía. `GET /pursuits/metrics` publica
 * ahora `radar_quality`, y esto lo presenta — **presenta**, no calcula: la
 * precisión, la tasa de cierre, el umbral y la ventana vienen ya resueltos
 * (ADR-014, invariante 1 de `web/AGENTS.md`).
 *
 * Regla de la que depende todo lo demás: por debajo del mínimo que declara la
 * respuesta (`minimo_por_banda`) **no se pinta un porcentaje**. Se dice «sin
 * datos suficientes» y se enseña la base. Un 100 % sobre dos cierres no es una
 * medida del Radar, es una anécdota con formato de dato.
 */

export type RadarQuality = NonNullable<PursuitMetrics["radar_quality"]>;
export type RadarBandaCalidad = NonNullable<RadarQuality["bandas"]>[number];
export type RadarBandaNombre = RadarBandaCalidad["banda"];

function bandaDe(calidad: RadarQuality, banda: RadarBandaNombre): RadarBandaCalidad | undefined {
  // `bandas` es opcional en el esquema (tiene default en el DTO), así que el
  // cliente generado la declara como posiblemente ausente.
  return (calidad.bandas ?? []).find((entrada) => entrada.banda === banda);
}

function porcentaje(valor: number): string {
  return `${Math.round(valor * 100)} %`;
}

/**
 * La frase de una sola banda, para ponerla junto al filtro del Radar.
 *
 * Devuelve `null` cuando no hay nada honesto que decir: sin métrica (ninguna
 * oportunidad lleva banda sellada) o sin ninguna oportunidad en esa banda. Un
 * hueco es mejor que una frase que no informa.
 */
export function RadarQualityNota({
  calidad,
  banda,
  className,
}: {
  calidad: RadarQuality | null | undefined;
  banda: RadarBandaNombre;
  className?: string;
}) {
  if (!calidad) return null;
  const datos = bandaDe(calidad, banda);
  if (!datos) return null;

  return (
    <p className={className ?? "text-[11px] leading-relaxed text-muted-foreground"}>
      {datos.precision === null || datos.precision === undefined ? (
        <>
          Precisión de la banda {banda} en tu organización:{" "}
          <span className="font-medium text-foreground/80">sin datos suficientes</span> (
          {datos.resueltas} de {calidad.minimo_por_banda} oportunidades resueltas necesarias)
        </>
      ) : (
        <>
          Precisión de la banda {banda} en tu organización:{" "}
          <span className="tf-tnum font-medium text-foreground">
            {datos.ganadas}/{datos.resueltas}
          </span>{" "}
          ({porcentaje(datos.precision)} de las resueltas)
        </>
      )}
    </p>
  );
}

/**
 * El cuadro completo: una línea por banda, más la ventana y la cobertura.
 *
 * La ventana y la cobertura no son decoración: «8 de 12» sin decir de cuándo ni
 * sobre cuántas oportunidades con banda sellada es un número sin universo.
 */
export function RadarQualityResumen({
  calidad,
  className,
}: {
  calidad: RadarQuality | null | undefined;
  className?: string;
}) {
  const bandas = calidad?.bandas ?? [];
  if (!calidad || bandas.length === 0) {
    return (
      <p className="text-[11.5px] leading-relaxed text-muted-foreground">
        Todavía no se puede medir si el Radar prioriza bien: ninguna oportunidad guarda la banda
        con la que se abrió. Se guarda al convertir una señal del Radar en oportunidad.
      </p>
    );
  }

  const desde = calidad.ventana_desde?.slice(0, 10);
  const hasta = calidad.ventana_hasta?.slice(0, 10);

  return (
    <div className={className}>
      <ul className="space-y-1.5">
        {bandas.map((banda) => (
          <li key={banda.banda} className="flex items-baseline justify-between gap-3 text-xs">
            <span className="font-medium">{banda.banda}</span>
            <span className="tf-tnum text-muted-foreground">
              {banda.precision === null || banda.precision === undefined
                ? `sin datos suficientes (${banda.resueltas}/${calidad.minimo_por_banda})`
                : `${banda.ganadas}/${banda.resueltas} ganadas · ${porcentaje(banda.precision)}`}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[10.5px] leading-relaxed text-muted-foreground">
        {desde && hasta ? `Ventana ${desde} → ${hasta}. ` : null}
        {calidad.pursuits_con_banda} de {calidad.pursuits_total} oportunidades guardan la banda
        con la que se abrieron; el resto es anterior a que se empezara a guardar.
      </p>
    </div>
  );
}
