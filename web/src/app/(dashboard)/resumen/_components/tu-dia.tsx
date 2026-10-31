"use client";

import { useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";
import {
  Aviso,
  EnlaceIr,
  PanelError,
  PanelTitle,
  StatCell,
  StatStrip,
  SUPERFICIE_PANEL,
} from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { useFilters } from "@/lib/filters";
import { cn, EMPTY, formatCompactCurrency, formatNumber } from "@/lib/utils";
import { type AgendaBanda, bandaDe } from "@/app/(dashboard)/mi-pipeline/_components/agenda/agenda-meta";
import { usePipelineAgenda } from "@/hooks/use-pursuits";
import { PuntosUnidad } from "./cifras-graficos";
import { SemanaEnCarriles } from "./tu-dia-semana";
import { semanaEnCarriles } from "./tu-dia-semana-data";

/**
 * Tu día — la banda que le faltaba al Resumen.
 *
 * El Resumen abría con «Total licitaciones 148.320 / Órganos únicos 2.104»:
 * una radiografía del mercado español en la pantalla de entrada de un producto
 * cuyo usuario abre la aplicación para saber **qué tiene que hacer hoy**. Todo
 * lo personal —plazos de presentación, tareas propias, contratos que entran en
 * su ventana de relicitación, señales sin triar— vivía dos clics más allá, en
 * la Agenda, y la entrada no daba ni una pista de que existiera.
 *
 * No hay analítica nueva: los contadores y las bandas de urgencia los calcula
 * el backend en `GET /pursuits/agenda` (ADR-014), el mismo endpoint que alimenta
 * la Agenda. Aquí sólo se recorta a los tres primeros tramos y se enseñan como
 * semana, con tres compromisos por día; la agenda completa sigue siendo su
 * pantalla.
 *
 * **El vocabulario visual se importa de la Agenda** (`agenda-meta.ts`): iconos,
 * chips y el nombre de cada clase de fecha. Con dos mapas separados, la misma
 * fila se leía de dos maneras según por dónde entraras — y el que estaba aquí
 * ni siquiera conocía `tarea` ni `contrato`, así que las pintaba a las dos con
 * el icono de otra cosa.
 *
 * **La semana va en carriles** (`tu-dia-semana.tsx`): lo vencido, hoy y un
 * carril por día con algo, colocado por los `dias_restantes` que manda el
 * backend. Cuatro filas en lista no decían si el viernes venía cargado; un
 * carril por día sí, y de un vistazo.
 *
 * **Plegada por defecto** (2026-10-31). La banda vive ahora en la columna
 * izquierda de la primera fila, junto al mercado de hoy, y los carriles medían
 * 260 px: empujaban «Desde tu última visita» y todo el mercado fuera de la
 * primera pantalla. Los contadores ya dicen cuánto hay; «Ver la semana» abre
 * qué, y la Agenda sigue siendo la pantalla completa.
 *
 * **Cada contador lleva sus puntos** (`cifras-graficos.tsx`): un cuadrado por
 * compromiso contado, en el tono de la cifra. Son recuentos pequeños, y «tres»
 * frente a «diecisiete» se ve antes de leer el número.
 */

/** Tramos que caben en una banda de entrada: lo vencido, lo de hoy y la semana. */
const URGENTES: AgendaBanda[] = ["vencida", "hoy", "semana"];

export function TuDia() {
  const { tecnologias, ccaas } = useFilters();
  const { data, isPending, error, refetch } = usePipelineAgenda({
    soloMios: false,
    // El backend acepta listas desde 2026-09-21: el ámbito entero viaja, así
    // que ya no hay que avisar de que sólo se aplicaba el primer valor.
    tecnologia: tecnologias.length ? tecnologias.join(",") : null,
    ccaa: ccaas.length ? ccaas.join(",") : null,
  });

  // Por el tramo de la fila y no por su urgencia: un plazo que pasó sin oferta
  // sigue teniendo urgencia `vencida`, pero ya no es trabajo de esta semana —
  // la Agenda lo pinta aparte, como algo que cerrar— y aquí llenaba el carril
  // «Vencido» con lo que no se puede hacer.
  const urgentes = useMemo(
    () => (data?.items ?? []).filter((item) => URGENTES.includes(bandaDe(item))),
    [data?.items],
  );
  // eslint-disable-next-line react-hooks/purity
  const hoy = useMemo(() => new Date(Date.now()), []);
  const tramos = useMemo(() => semanaEnCarriles(urgentes, hoy), [urgentes, hoy]);
  const [verSemana, setVerSemana] = useState(false);

  // Los contadores de la franja de la Agenda, que miran solo las oportunidades
  // vivas. Una API anterior a ellos no los manda: ahí se enseñan los de
  // siempre, que es lo que esta banda pintaba, en vez de cuatro rayas.
  const kpis = data?.kpis;
  const franja = data?.contadores;
  const cifras = kpis && {
    plazos: franja?.plazo_semana ?? kpis.vence_semana,
    plazosImporte: franja?.plazo_semana_importe_eur ?? kpis.vence_semana_importe_eur,
    acciones: franja?.accion_vencida ?? kpis.acciones_hoy,
    goNoGo: franja?.go_no_go ?? kpis.go_no_go_pendientes,
    sinAccion: franja?.sin_paso ?? kpis.sin_proxima_accion,
  };
  const pasados = franja?.plazo_pasado ?? 0;
  const recortada =
    data?.pursuits_truncados || data?.tareas_truncadas || data?.senales_truncadas;

  return (
    <section aria-labelledby="resumen-tu-dia">
      <PanelTitle
        as="h2"
        id="resumen-tu-dia"
        title="Tu día"
        hint="de tu organización"
        actions={
          <span className="flex items-center gap-2">
            {urgentes.length > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-expanded={verSemana}
                aria-controls="resumen-tu-dia-semana"
                onClick={() => setVerSemana((abierta) => !abierta)}
              >
                {verSemana ? "Ocultar la semana" : `Ver la semana · ${formatNumber(urgentes.length)}`}
                <ChevronDown
                  className={cn("transition-transform duration-150", verSemana && "rotate-180")}
                  aria-hidden="true"
                />
              </Button>
            )}
            <EnlaceIr href="/mi-pipeline?vista=agenda">Abrir agenda</EnlaceIr>
          </span>
        }
        className="mb-2.5"
      />

      {error ? (
        // Un solo aviso por fallo (D6): el toast lo calla el `meta` de la
        // consulta, que vive en `usePipelineAgenda` (`hooks/use-pursuits.ts`).
        <PanelError
          title="No se pudo cargar tu agenda"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : (
        <>
          {/* Los contadores encima y la semana a todo el ancho: al lado, los
              carriles no cabían y recortaban los títulos. */}
          <div className="grid grid-cols-1 gap-2.5">
            <StatStrip columns={4}>
              <StatCell
              label="Plazos en 7 días"
              loading={isPending}
              value={cifras ? formatNumber(cifras.plazos) : EMPTY}
              tono={cifras && cifras.plazos > 0 ? "destructive" : undefined}
              grafico={cifras && <PuntosUnidad n={cifras.plazos} tono="destructive" />}
              hint={
                cifras && cifras.plazos > 0
                  ? `${formatCompactCurrency(cifras.plazosImporte)} en juego`
                  : "Oportunidades que aún se pueden presentar"
              }
            />
            <StatCell
              label="Acciones hoy o vencidas"
              loading={isPending}
              value={cifras ? formatNumber(cifras.acciones) : EMPTY}
              grafico={cifras && <PuntosUnidad n={cifras.acciones} />}
              hint="Tareas propias con fecha pasada o de hoy"
            />
            <StatCell
              label="Go/No-Go pendientes"
              loading={isPending}
              value={cifras ? formatNumber(cifras.goNoGo) : EMPTY}
              grafico={cifras && <PuntosUnidad n={cifras.goNoGo} />}
              hint="Sin decisión tomada"
            />
            <StatCell
              label="Sin próxima acción"
              loading={isPending}
              value={cifras ? formatNumber(cifras.sinAccion) : EMPTY}
              tono={cifras && cifras.sinAccion > 0 ? "warning" : undefined}
              grafico={cifras && <PuntosUnidad n={cifras.sinAccion} tono="warning" />}
              hint="Oportunidades sin tarea abierta"
            />
            </StatStrip>

            {/* Lo que salió de los contadores no se calla: son oportunidades
                que nadie cerró, y el sitio donde se cierran es la Agenda. */}
            {pasados > 0 && (
              <Aviso
                tone="info"
                action={
                  <EnlaceIr href="/mi-pipeline?filtro=plazo_pasado">
                    {pasados === 1 ? "Cerrarla en la agenda" : "Cerrarlas en la agenda"}
                  </EnlaceIr>
                }
              >
                {/* «Ya no admite oferta» y no «plazo pasado»: cuentan también
                    las que están sobre una licitación resuelta, tenga o no
                    fecha límite. */}
                {pasados === 1
                  ? "1 oportunidad sigue abierta y ya no admite oferta."
                  : `${formatNumber(pasados)} oportunidades siguen abiertas y ya no admiten oferta.`}
              </Aviso>
            )}

            {/* Una semana sin nada es una línea, no un panel de 150 px: con los
                cuatro contadores a cero encima, el vacío ya está dicho, y el
                panel grande empujaba el mercado media pantalla abajo. */}
            {!isPending && urgentes.length === 0 && (
              <div
                className={cn(
                  SUPERFICIE_PANEL,
                  "flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 px-3.5 py-2.5",
                )}
              >
                {/* `basis-64`: por debajo de ese ancho el enlace baja de línea en vez
                    de estrujar la frase en una columna de tres palabras. */}
                <p className="min-w-0 flex-1 basis-64 text-tf-meta">
                  <span className="font-medium">Nada vence esta semana.</span>{" "}
                  <span className="text-muted-foreground">
                    Aquí salen los plazos, las tareas y las renovaciones de los próximos siete días.
                  </span>
                </p>
                <EnlaceIr href="/radar" className="flex-none">
                  Buscar oportunidades en el Radar
                </EnlaceIr>
              </div>
            )}

            {verSemana && urgentes.length > 0 && (
              <div id="resumen-tu-dia-semana" className={cn(SUPERFICIE_PANEL, "min-w-0 p-2.5")}>
                <SemanaEnCarriles tramos={tramos} />
              </div>
            )}
          </div>

          {/* La lista tiene un tope y se declara: unos contadores
              silenciosamente bajos se leen como «no tengo trabajo». */}
          {recortada && (
            <Aviso tone="warning" className="mt-2">
              Hay más compromisos de los que caben en la lista: los contadores solo cuentan los que
              aparecen.
            </Aviso>
          )}
        </>
      )}
    </section>
  );
}
