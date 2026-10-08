"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { EnlaceIr, Panel, PanelEmpty, PanelError, PanelTitle, Segmented } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters } from "@/lib/filters";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { formatNumber } from "@/lib/utils";
import type { TimelineScatterResult } from "@/lib/api-types";
import { ITEMS_PER_PAGE, TIMELINE_MAX, esNueva, type TimelineItem } from "./types";
import { ordenarPublicaciones, type DireccionOrden } from "./ultimas-publicaciones-data";
import { ListaPublicacionesMovil, TablaPublicaciones } from "./ultimas-publicaciones-tabla";
import { useNovedades } from "../_hooks/use-novedades";

/** Fichas en el teléfono: las más recientes; el resto, en Detalle. */
const FILAS_MOVIL = 5;

type Vista = "todas" | "nuevas";

/**
 * Últimas publicaciones: la tabla que desglosa el panel de publicaciones.
 *
 * Ocho columnas ordenables, paginación de diez y el tope del endpoint
 * declarado, porque «1–10 de 1.000» se leía como el total del ámbito cuando es
 * el techo de `/resumen/timeline`. **Origen** dice de qué portal viene cada
 * expediente (`fuente`, con los nombres de `lib/fuentes`). El importe lleva una
 * barra logarítmica para comparar de un vistazo, y la fecha dice «hoy» y
 * «ayer» con la hora, que es casi todo lo que la tabla enseña.
 *
 * **Las filas nuevas** (después de tu última visita) llevan el punto de
 * `esNueva`, con su leyenda en la cabecera cuando hay alguna, y «Nuevas» deja
 * solo esas. El recuento autoritativo es la tarjeta «Nuevas» de «Mercado
 * abierto»; aquí se filtran las filas que ya llegaron.
 *
 * En un teléfono la tabla pasa a fichas con las cinco más recientes.
 */
export function UltimasPublicaciones() {
  const { rango } = useFilters();
  const novedades = useNovedades();
  const corteNovedades = novedades.data?.desde ?? null;

  const [pagina, setPagina] = useState(0);
  const [clave, setClave] = useState<keyof TimelineItem>("fecha_publicacion");
  const [direccion, setDireccion] = useState<DireccionOrden>("desc");
  const [vista, setVista] = useState<Vista>("todas");

  // Ventana por defecto de 30 días cuando el ámbito no fija fecha de inicio.
  // eslint-disable-next-line react-hooks/purity
  const desde = rango.desde ?? new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
  const timeline = useFilteredQuery<TimelineScatterResult>(
    ["analytics", "resumen", "timeline", desde],
    "/api/v1/analytics/resumen/timeline",
    // El fallo lo pinta el panel: sin toast encima.
    { staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
    { fecha_desde: desde },
  );

  const items = useMemo(() => (timeline.data?.items ?? []) as TimelineItem[], [timeline.data?.items]);
  const nuevas = useMemo(
    () => items.filter((item) => esNueva(item.fecha_publicacion, corteNovedades)),
    [items, corteNovedades],
  );
  const hayNuevas = nuevas.length > 0;
  const soloNuevas = vista === "nuevas" && hayNuevas;
  const base = soloNuevas ? nuevas : items;
  const topeAlcanzado = items.length >= TIMELINE_MAX;

  const ordenadas = useMemo(() => ordenarPublicaciones(base, clave, direccion), [base, clave, direccion]);
  // eslint-disable-next-line react-hooks/purity
  const ahora = useMemo(() => new Date(Date.now()), []);

  // Ordenar por otra columna vuelve a la primera página: «página 3 de otro
  // criterio» no señala las mismas filas.
  const ordenar = (nueva: keyof TimelineItem) => {
    if (clave === nueva) {
      setDireccion((actual) => (actual === "asc" ? "desc" : "asc"));
    } else {
      setClave(nueva);
      setDireccion("asc");
    }
    setPagina(0);
  };

  const cambiarVista = (siguiente: Vista) => {
    setVista(siguiente);
    setPagina(0);
  };

  const paginas = Math.max(1, Math.ceil(ordenadas.length / ITEMS_PER_PAGE));
  const paginaVisible = Math.min(pagina, paginas - 1);
  const filas = ordenadas.slice(paginaVisible * ITEMS_PER_PAGE, (paginaVisible + 1) * ITEMS_PER_PAGE);
  const rangoFilas =
    ordenadas.length === 0
      ? "—"
      : `${paginaVisible * ITEMS_PER_PAGE + 1}–${Math.min((paginaVisible + 1) * ITEMS_PER_PAGE, ordenadas.length)} de ${formatNumber(ordenadas.length)}${soloNuevas ? " nuevas" : topeAlcanzado ? " más recientes" : ""}`;

  return (
    <Panel className="mb-5.5">
      <PanelTitle
        as="h2"
        title="Últimas publicaciones"
        hint={
          hayNuevas ? (
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 flex-none rounded-full bg-primary" aria-hidden="true" />
              nuevas desde tu última visita
            </span>
          ) : undefined
        }
        actions={<span className="tf-tnum text-tf-micro text-muted-foreground">{rangoFilas}</span>}
      />

      {hayNuevas && (
        <Segmented
          className="mb-2.5"
          aria-label="Qué publicaciones ver"
          value={vista}
          onChange={cambiarVista}
          options={[
            { value: "todas", label: "Todas" },
            { value: "nuevas", label: "Nuevas", count: formatNumber(nuevas.length) },
          ]}
        />
      )}

      {topeAlcanzado && !soloNuevas && (
        <p className="mb-2 text-tf-micro text-muted-foreground">
          El orden se aplica a las {formatNumber(TIMELINE_MAX)} publicaciones más recientes del ámbito,
          no a todas: para verlas todas,{" "}
          <Link href="/detalle" className="text-primary hover:underline">
            abre el listado completo
          </Link>
          .
        </p>
      )}

      {timeline.error && (
        <PanelError
          variant="inline"
          title="No se pudo cargar el listado"
          error={timeline.error}
          onRetry={() => void timeline.refetch()}
        />
      )}

      {!timeline.error && (
        <>
          <div className="hidden md:block">
            <TablaPublicaciones
              filas={filas}
              cargando={timeline.isLoading}
              clave={clave}
              direccion={direccion}
              onOrdenar={ordenar}
              corteNovedades={corteNovedades}
              ahora={ahora}
            />
          </div>
          <div className="md:hidden">
            <ListaPublicacionesMovil
              filas={ordenadas.slice(0, FILAS_MOVIL)}
              corteNovedades={corteNovedades}
              ahora={ahora}
            />
            {ordenadas.length > FILAS_MOVIL && (
              <EnlaceIr href="/detalle" className="mt-2">
                Ver todas en Detalle
              </EnlaceIr>
            )}
          </div>
        </>
      )}

      {!timeline.error && !timeline.isLoading && filas.length === 0 && (
        <PanelEmpty title="Sin publicaciones en la ventana" hint="Amplía las fechas del ámbito para ver más." />
      )}

      {ordenadas.length > ITEMS_PER_PAGE && (
        <nav
          aria-label="Paginación de publicaciones"
          className="mt-2.5 hidden items-center gap-2 border-t border-border/40 pt-2.5 md:flex"
        >
          <span className="text-tf-micro text-muted-foreground">
            La barra del importe va en escala logarítmica, de 100 € a 10 M€.
          </span>
          <div className="flex-1" />
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label="Página anterior"
            disabled={paginaVisible === 0}
            onClick={() => setPagina(Math.max(0, paginaVisible - 1))}
          >
            <ChevronLeft aria-hidden="true" />
          </Button>
          <span className="tf-tnum text-tf-micro text-muted-foreground">
            {paginaVisible + 1} / {paginas}
          </span>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label="Página siguiente"
            disabled={paginaVisible >= paginas - 1}
            onClick={() => setPagina(Math.min(paginas - 1, paginaVisible + 1))}
          >
            <ChevronRight aria-hidden="true" />
          </Button>
        </nav>
      )}
    </Panel>
  );
}
