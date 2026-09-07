"use client";

import { useState } from "react";
import { Panel, PanelError, PanelLoading, PanelTabs, PanelTitle } from "@/components/console/panel";
import { useFiltrosIgnorados } from "./alcance";
import { AvisoAlcance } from "./aviso-alcance";
import { usePublicaciones } from "../_hooks/use-publicaciones";
import { DispersionScatter } from "./publicaciones/dispersion-scatter";
import { ImportesHistograma } from "./publicaciones/importes-histograma";
import { RitmoChart } from "./publicaciones/ritmo-chart";
import { ALTO, HINTS, TABS, type Corte } from "./publicaciones/publicaciones-data";

/**
 * Publicaciones del periodo — tres cortes del mismo periodo.
 *
 * La nube de puntos era el objeto más grande de la pantalla y el menos
 * accionable, por cuatro razones que sólo se ven con datos reales:
 *
 * 1. **Medía el 3 % del periodo.** `/resumen/timeline` devolvía las 1.000
 *    publicaciones **más recientes**; en el corpus real eso son **48 horas de
 *    una ventana de 30 días** (29.808 expedientes). El panel se llamaba «en el
 *    periodo» y enseñaba dos días. Arreglado en backend: el endpoint acepta
 *    `muestra=true` y reparte las 1.000 filas por toda la ventana (una de cada
 *    `ceil(total/1000)`), así que la nube pasa de cubrir 2 días a cubrir los
 *    30 pedidos. El flag es opt-in porque la tabla de «últimas publicaciones»
 *    necesita exactamente lo contrario.
 * 2. **El eje Y estaba aplastado.** El 71 % de los importes del periodo está
 *    **por debajo de 1.000 €** y el eje llegaba a 16 M: casi todos los puntos
 *    caían en la franja de 2 px pegada al eje.
 * 3. **El color por estado no informaba.** Condicionado a «publicado en los
 *    últimos días», el estado es casi constante por construcción.
 * 4. **No respondía a ninguna pregunta.** Ni ordena, ni compara, ni tiene
 *    tendencia.
 *
 * De ahí los tres cortes: **Ritmo** (publicaciones por día), **Importes** (el
 * histograma logarítmico) y **Dispersión** (la nube conservada, ahora sobre la
 * muestra repartida y con eje logarítmico). Los dos primeros salen de una sola
 * llamada agregada en backend; el detalle de las consultas y de lo que cada
 * cifra declara está en `_hooks/use-publicaciones.ts` y en cada corte.
 *
 * Aquí queda el reparto: qué corte se ve y qué estado —error, carga o dato— se
 * pinta, que es común a los tres.
 */
export function PublicacionesPanel() {
  const [corte, setCorte] = useState<Corte>("ritmo");
  const ignorados = useFiltrosIgnorados();
  const publicaciones = usePublicaciones(corte);

  return (
    <Panel>
      <PanelTitle title="Publicaciones en el periodo" hint={HINTS[corte]} />
      <AvisoAlcance ignorados={ignorados} />
      <div className="mb-2.5">
        <PanelTabs tabs={TABS} value={corte} onChange={setCorte} label="Corte de las publicaciones" />
      </div>

      {publicaciones.error ? (
        <PanelError
          title="No se pudieron cargar las publicaciones"
          detail={(publicaciones.error as Error).message}
          onRetry={publicaciones.refetch}
          height={ALTO}
        />
      ) : publicaciones.cargando ? (
        <PanelLoading height={ALTO} />
      ) : corte === "ritmo" ? (
        <RitmoChart
          serie={publicaciones.serie}
          serieTruncada={publicaciones.serieTruncada}
          ventana={publicaciones.ventana}
          onDia={publicaciones.acotarADia}
        />
      ) : corte === "importes" ? (
        <ImportesHistograma
          histograma={publicaciones.histograma}
          total={publicaciones.totalHistograma}
          maximo={publicaciones.maxHistograma}
        />
      ) : (
        <DispersionScatter
          puntos={publicaciones.scatterData}
          leyenda={publicaciones.leyenda}
          muestreado={publicaciones.muestreado}
          totalVentana={publicaciones.totalVentana}
          sinImporte={publicaciones.sinImporte}
          ventana={publicaciones.ventana}
        />
      )}
    </Panel>
  );
}
