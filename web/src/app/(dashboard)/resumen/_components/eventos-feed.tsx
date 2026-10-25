"use client";

import Link from "next/link";
import { Activity } from "lucide-react";
import { Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters } from "@/lib/filters";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { useMemo, useState } from "react";
import { formatDate, formatNumber, truncate } from "@/lib/utils";
import type { EventosFeedResult } from "@/lib/api-types";
import { agruparPorDia } from "@/lib/agrupar-por-dia";
import { BarraApilada, tramosApilados } from "./contexto-graficos";
import { colorDeTipo, ImporteDelta, LeyendaTipos, TIPO_ICON, TIPO_LABEL } from "./eventos-tipos";

const MAX_FILAS = 8;

/** Ventana del feed en palabras, para que el panel diga qué está midiendo
 * cuando el ámbito mueve las fechas. */
function ventanaLabel(desde: string | null, hasta: string | null): string {
  if (desde && hasta) return `Del ${formatDate(desde)} al ${formatDate(hasta)}`;
  if (desde) return `Desde el ${formatDate(desde)}`;
  if (hasta) return `Hasta el ${formatDate(hasta)}`;
  return "Últimos 30 días";
}

/** Feed de movimientos de contrato (prórrogas, modificaciones, anulaciones…)
 * — GET /api/v1/eventos.
 *
 * Es el único panel del Resumen que aplica **los siete** filtros del ámbito:
 * las fechas acotan aquí *el movimiento* (cuándo cambió el contrato), no la
 * publicación del expediente — ver el docstring de `GET /eventos`.
 *
 * Vestía todavía la `Card` heredada (título de 16 px, filas de 14) en una
 * pantalla cuyo resto está a 11 px: era el bloque que delataba que la página
 * venía de dos generaciones distintas. Ahora usa el vocabulario de panel de la
 * consola, como el resto.
 */
export function EventosFeed() {
  const { rango } = useFilters();
  const { data, isLoading, error, refetch } = useFilteredQuery<EventosFeedResult>(
    ["eventos", "feed"],
    "/api/v1/eventos",
    // El fallo se pinta en el sitio del panel: sin toast encima.
    { staleTime: 2 * 60 * 1000, meta: META_ERROR_EN_LINEA },
    { dias: "30", limit: "20" },
  );
  // Con un tipo de la leyenda pulsado, la lista es otra petición —la misma con
  // `tipo`—; la barra y la leyenda siguen con la ventana entera. Sin datos
  // previos de relleno: cambiar de tipo no enseña un instante los del anterior.
  const [tipo, setTipo] = useState<string | null>(null);
  const filtrada = useFilteredQuery<EventosFeedResult>(
    ["eventos", "feed"],
    "/api/v1/eventos",
    { staleTime: 2 * 60 * 1000, meta: META_ERROR_EN_LINEA, enabled: tipo !== null },
    { dias: "30", limit: "20", ...(tipo ? { tipo } : {}) },
    true,
  );
  const lista = tipo ? filtrada.data : data;

  const items = lista?.items ?? [];
  const visibles = items.slice(0, MAX_FILAS);
  // eslint-disable-next-line react-hooks/purity
  const ahora = useMemo(() => new Date(Date.now()), []);
  const dias = useMemo(() => agruparPorDia(visibles, ahora), [visibles, ahora]);
  // El reparto y el total cuentan la ventana entera, no las filas pedidas: los
  // da el backend (`por_tipo`, `total`), y la lista es la muestra más reciente.
  // Una respuesta sin `total` cae al tamaño de la muestra, como antes. Con un
  // tipo pulsado, el pie cuenta los de ese tipo.
  const total = lista?.total || items.length;
  const totalVentana = data?.total || (data?.items.length ?? 0);
  const tramos = useMemo(
    () =>
      tramosApilados(
        (data?.por_tipo ?? []).map((t) => ({ estado: t.tipo, n: t.n, color: colorDeTipo(t.tipo) })),
      ),
    [data?.por_tipo],
  );

  return (
    <Panel>
      <PanelTitle
        // `h2`, como «Publicaciones»: es una sección de la página, y sus días van en `h3`.
        as="h2"
        title="Movimientos del mercado"
        hint={`${ventanaLabel(rango.desde, rango.hasta)} · del ámbito`}
        actions={
          !error && total > visibles.length ? (
            <span className="tf-tnum text-tf-micro text-muted-foreground">
              {visibles.length} de {formatNumber(total)}
            </span>
          ) : undefined
        }
      />

      {/* El fallo va dentro del panel, bajo su título: la sección no pierde
          su nombre ni su sitio en la página. */}
      {error ? (
        <PanelError
          variant="inline"
          title="No se pudieron cargar los movimientos"
          error={error}
          onRetry={() => void refetch()}
          height={180}
        />
      ) : isLoading ? (
        <div className="flex flex-col gap-1.5">
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} className="h-7 w-full rounded-sm" />
          ))}
        </div>
      ) : (data?.items.length ?? 0) === 0 ? (
        <PanelEmpty
          title="Ningún contrato se ha movido en la ventana"
          hint="Prórrogas, modificaciones, adjudicaciones y anulaciones del ámbito salen aquí. Amplía las fechas para ver más."
        />
      ) : (
        // Arriba, de qué se compone la ventana; debajo, la línea de tiempo: un
        // grupo por día y, en cada movimiento, un disco con el icono de su
        // clase —del color de su tramo— sobre la línea vertical.
        <div className="flex flex-col gap-1">
          {tramos.length > 0 && (
            <div className="mb-2 flex flex-col gap-2 border-b border-divider pb-3">
              <BarraApilada tramos={tramos} total={totalVentana} activos={tipo ? [tipo] : []} />
              <LeyendaTipos tramos={tramos} activo={tipo} onTipo={setTipo} />
            </div>
          )}
          {tipo && filtrada.error ? (
            <PanelError
              variant="inline"
              title="No se pudieron cargar los movimientos de este tipo"
              error={filtrada.error}
              onRetry={() => void filtrada.refetch()}
              height={120}
            />
          ) : tipo && filtrada.isLoading ? (
            <div className="flex flex-col gap-1.5">
              {Array.from({ length: 3 }, (_, index) => (
                <Skeleton key={index} className="h-7 w-full rounded-sm" />
              ))}
            </div>
          ) : tipo && items.length === 0 ? (
            <p className="py-2 text-tf-meta text-muted-foreground">Ningún movimiento de este tipo en la ventana.</p>
          ) : null}
          {dias.map((dia) => (
            <section key={dia.clave} aria-label={dia.etiqueta}>
              <h3 className="pb-0.5 pl-9 text-tf-micro font-semibold text-muted-foreground">{dia.etiqueta}</h3>
              <ul className="relative before:absolute before:bottom-0 before:left-[13px] before:top-0 before:w-px before:bg-divider">
                {dia.eventos.map((evento, indice) => {
                  const Icon = TIPO_ICON[evento.tipo] ?? Activity;
                  return (
                    <li key={`${evento.licitacion_id}-${evento.tipo}-${indice}`}>
                      <Link
                        href={`/detalle?lic=${encodeURIComponent(evento.licitacion_id)}`}
                        className="relative flex items-start gap-2.5 rounded-md py-1.5 pr-1 transition-colors hover:bg-primary-hover active:bg-primary-selected active:duration-0"
                      >
                        <span className="grid h-7 w-7 flex-none place-items-center rounded-full border border-divider bg-card">
                          <Icon className="h-3.5 w-3.5" color={colorDeTipo(evento.tipo)} aria-hidden="true" />
                        </span>
                        <span className="flex min-w-0 flex-1 flex-col">
                          <span className="flex items-baseline gap-2">
                            <span className="min-w-0 flex-1 truncate text-tf-micro font-semibold">
                              {TIPO_LABEL[evento.tipo] ?? evento.tipo}
                            </span>
                            <ImporteDelta value={evento.importe_delta} />
                          </span>
                          <span className="truncate text-tf-meta">
                            {truncate(evento.titulo ?? evento.licitacion_id, 90)}
                          </span>
                          {evento.organo_contratacion && (
                            <span className="truncate text-tf-micro text-muted-foreground">
                              {evento.organo_contratacion}
                            </span>
                          )}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      )}
    </Panel>
  );
}
