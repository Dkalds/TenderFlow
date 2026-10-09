/**
 * ¿El Radar ordena bien? La precisión de cada banda, en escalera.
 *
 * La promesa del Radar es que lo que pone arriba se gana más: si ordena bien,
 * la precisión baja de Caliente a Descarte. Si la escalera baja o no lo dice
 * el backend (`radar_ordena_bien`), no la pantalla; aquí sólo se dibuja cada
 * banda con su precisión y, por debajo del mínimo, el hueco con lo que falta.
 *
 * Es una cohorte —lo que se **abrió** desde cada banda en el periodo y cómo
 * acabó—, no una ventana de cierres como el resto de la pantalla, y el panel
 * lo dice. El reparto completo, con tasa de cierre, está en Rendimiento.
 */
import Link from "next/link";

import { Panel, PanelTitle } from "@/components/console/panel";
import { CoberturaRadar, SinBandaSellada } from "@/components/pursuits/radar-quality";
import type { Schemas } from "@/lib/api-types";
import { formatNumber } from "@/lib/utils";

type Cuadro = Schemas["CuadroDireccion"];

function Veredicto({ ordena }: { ordena: boolean | null | undefined }) {
  if (ordena == null) {
    return (
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Para ver la escalera hacen falta al menos dos bandas con base.
      </p>
    );
  }
  return ordena ? (
    <p className="mb-3 text-tf-meta font-medium text-success">
      Ordena bien: lo que pone más arriba se gana más.
    </p>
  ) : (
    <p className="mb-3 text-tf-meta font-medium text-warning">
      La escalera no baja: alguna banda de abajo gana más que la de arriba.
    </p>
  );
}

export function RadarDireccion({ cuadro }: { cuadro: Cuadro }) {
  const calidad = cuadro.radar_quality;
  const bandas = calidad?.bandas ?? [];
  return (
    <Panel>
      <PanelTitle as="h2" title="¿El Radar ordena bien?" hint="Abiertas en el periodo, por banda de entrada" />
      {!calidad || bandas.length === 0 ? (
        <SinBandaSellada />
      ) : (
        <>
          <Veredicto ordena={cuadro.radar_ordena_bien} />
          <ul className="space-y-1.5" aria-label="Precisión por banda">
            {bandas.map((banda) => (
              <li key={banda.banda} className="grid grid-cols-[5.5rem_1fr_7.5rem] items-center gap-3">
                <span className="text-tf-meta font-medium">{banda.banda}</span>
                {banda.precision != null ? (
                  <svg className="h-3 w-full" viewBox="0 0 100 1" preserveAspectRatio="none" aria-hidden="true">
                    <rect className="fill-secondary/60" width="100" height="1" />
                    <rect className="fill-primary/60" height="1" width={Math.max(1, banda.precision * 100)} />
                  </svg>
                ) : (
                  <span className="text-tf-micro text-muted-foreground">
                    Sin base ({formatNumber(banda.resueltas)}/{calidad.minimo_por_banda})
                  </span>
                )}
                <span className="tf-tnum text-right text-tf-meta">
                  {banda.precision != null ? (
                    <>
                      <span className="font-semibold">{Math.round(banda.precision * 100)} %</span>
                      <span className="text-muted-foreground">
                        {" "}
                        · {formatNumber(banda.ganadas)}/{formatNumber(banda.resueltas)}
                      </span>
                    </>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
          <CoberturaRadar calidad={calidad} />
        </>
      )}
      {/* Al pie y no en la cabecera: en un teléfono, junto al título y la pista, se cortaba. */}
      <Link
        href="/oportunidades?vista=rendimiento"
        className="mt-3 inline-block text-tf-meta text-primary hover:underline"
      >
        Tasa de cierre por banda en Rendimiento
      </Link>
    </Panel>
  );
}
