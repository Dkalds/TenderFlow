"use client";

/**
 * La cronología: los dos carriles, la barra de filtro y atajos, y las filas
 * agrupadas por los tramos que ya vienen de la API.
 *
 * **Dos carriles y no una lista.** Lo que la organización ya decidió trabajar
 * —plazos, acciones y contratos propios— y lo que las reglas *proponen* son dos
 * trabajos distintos: uno se ejecuta, el otro se tria. Mezclados, cincuenta
 * señales sin triar enterraban las cuatro cosas que vencen esta semana. Repartir
 * por `kind` no es reordenar: dentro de cada carril las filas conservan el orden
 * y el tramo que trae la API (ADR-014).
 *
 * **Sin reglas no hay segundo carril.** Las señales salen de las reglas de Mi
 * Watchlist; quien no tiene ninguna no tiene bandeja, y una pestaña «Por triar
 * · 0» permanente parecía una bandeja ya triada. En su lugar va una línea que
 * dice cómo llenarla.
 *
 * Los conteos de las pestañas y de los tramos describen **lo listado**, no el
 * universo: son el tamaño de la lista que hay debajo. Los agregados sobre el
 * ámbito completo son los contadores de la franja, y esos los calcula la API.
 */

import * as React from "react";
import { cn, formatNumber } from "@/lib/utils";
import { useDensity } from "@/lib/density";
import { EnlaceIr, PanelEmpty, PanelTabs } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { Agenda } from "../../_hooks/use-agenda";
import { AgendaFila } from "./agenda-fila";
import {
  atajosPara,
  bandaDe,
  BANDAS,
  type Carril,
  claveDe,
  CONTADORES,
  tareasAnidadas,
} from "./agenda-meta";

const VACIO: Record<Carril, { title: string; hint: string }> = {
  compromisos: {
    title: "Sin compromisos por delante",
    hint: "Sigue señales desde el Radar para abrir oportunidades, o apunta una tarea en la ficha de una que ya tengas.",
  },
  triaje: {
    title: "Nada sin triar",
    hint: "Las señales llegan de tus reglas de Mi Watchlist. Crea o afina una para que la bandeja se llene.",
  },
};

export function AgendaLista({ agenda }: { agenda: Agenda }) {
  const compact = useDensity((s) => s.compact);
  // La densidad es de la tabla: la ficha móvil tiene su propio relleno, y
  // apretarla a 6 px de aire vertical no la hace más legible, solo más pequeña.
  const rowPad = compact ? "md:py-1.5" : "md:py-2.5";
  const { items, isLoading, activeIndex, carril, filtro } = agenda;
  const atajos = atajosPara(items);
  const filtrado = CONTADORES.find((contador) => contador.key === filtro);

  // El scroll de la fila activa vive donde vive la lista: el ref apunta a este
  // contenedor, y sacarlo al hook obligaba a pasearlo por props.
  const listRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>('[data-active="true"]');
    node?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, carril, filtro]);

  return (
    <section className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-border/60 bg-card md:min-h-0">
      <div className="flex flex-none flex-wrap items-center gap-2 border-b border-border/60 px-3 py-2 md:px-3.5">
        {agenda.sinReglas ? (
          <h2 className="px-1 text-tf-body font-semibold">Compromisos</h2>
        ) : (
          // `PanelTabs` trae su propia línea inferior, pensada para separarse
          // del gráfico que hay debajo; aquí la cabecera ya tiene la suya.
          <PanelTabs
            label="Carriles de la agenda"
            value={carril}
            onChange={agenda.setCarril}
            className="border-b-0 pb-0"
            tabs={[
              {
                key: "compromisos" as Carril,
                label: "Compromisos",
                // Sin número mientras carga: un «0» ahí se leía como «no
                // tienes nada» medio segundo antes de que llegara la lista.
                badge: isLoading ? undefined : agenda.conteos.compromisos,
              },
              {
                key: "triaje" as Carril,
                label: "Por triar",
                badge: isLoading ? undefined : agenda.conteos.triaje,
              },
            ]}
          />
        )}
        <button
          type="button"
          aria-pressed={agenda.soloMios}
          onClick={agenda.alternarSoloMios}
          className={cn(
            // 32 px de alto en móvil: el filtro se pulsa con el pulgar.
            "tf-pressable h-8 flex-none rounded-md border px-2.5 text-tf-meta font-medium md:h-7",
            agenda.soloMios
              ? "border-primary/30 bg-primary/10 text-primary"
              : "border-border/70 text-muted-foreground hover:text-foreground",
          )}
        >
          Solo míos
        </button>
        <span className="truncate text-tf-micro text-muted-foreground">
          {isLoading
            ? "Cargando agenda…"
            : filtrado
              ? `${formatNumber(items.length)} con el filtro «${filtrado.label}»`
              : `${formatNumber(items.length)} en este carril`}
        </span>
        {agenda.sinReglas && (
          <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-tf-micro text-muted-foreground">
            Aún no llega nada por triar.
            <EnlaceIr href="/mi-watchlist" className="text-tf-micro">
              Crea tu primera regla
            </EnlaceIr>
          </span>
        )}
        <div className="flex-1" />
        <div className="hidden items-center gap-2.5 md:flex">
          {atajos.map((shortcut) => (
            <span
              key={shortcut.key}
              className="flex items-center gap-1 text-tf-micro text-muted-foreground/70"
            >
              <kbd className="rounded-sm border border-border/70 bg-secondary px-1 font-mono text-tf-micro">
                {shortcut.key}
              </kbd>
              {shortcut.label}
            </span>
          ))}
        </div>
      </div>

      {/* En móvil la lista crece con su contenido y la que se desplaza es la
          página: una caja con scroll propio (`70vh`) dentro de otra que también
          lo tenía atrapaba el pulgar en la de dentro. Desde `md` la lista ocupa
          el alto que queda y sí lleva el suyo, para que la cabecera, los
          contadores y el inspector no se vayan al desplazarla. */}
      <div
        data-slot="agenda-filas"
        ref={listRef}
        className="relative min-h-[240px] md:min-h-0 md:flex-1 md:overflow-y-auto"
      >
        {isLoading ? (
          <div className="flex flex-col gap-2.5 p-3.5">
            {Array.from({ length: 8 }, (_, index) => (
              <Skeleton key={index} className="h-10 rounded-md" />
            ))}
          </div>
        ) : items.length === 0 && filtrado ? (
          // El vacío del filtro no es el de la agenda: decir «Sin compromisos
          // por delante» con los demás a un clic habría sido mentira. Pasa al
          // resolver la última fila de un contador con el filtro puesto.
          <PanelEmpty
            title={`Nada en «${filtrado.label}»`}
            hint="Ya no queda ninguna fila en este contador. El resto de tus compromisos sigue ahí."
            action={
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => agenda.alternarFiltro(filtrado.key)}
              >
                Quitar el filtro
              </Button>
            }
          />
        ) : items.length === 0 ? (
          <PanelEmpty
            title={VACIO[carril].title}
            hint={VACIO[carril].hint}
            action={
              <Button type="button" variant="outline" size="sm" onClick={agenda.irAlRadar}>
                Abrir el Radar
              </Button>
            }
          />
        ) : (
          BANDAS.map((banda) => {
            const filas = items
              .map((item, index) => ({ item, index }))
              .filter(({ item }) => bandaDe(item) === banda.key);
            if (!filas.length) return null;
            const anidadas = tareasAnidadas(filas.map(({ item }) => item));
            return (
              <React.Fragment key={banda.key}>
                {/* Pegajosa solo desde `md`, donde la lista tiene su propio
                    scroll. En móvil se desplaza la página, cuyo cuerpo lleva
                    relleno arriba: una cabecera pegada ahí se quedaba 16 px
                    por debajo del borde, con las filas asomando por encima. */}
                <div className="z-10 border-b border-border/50 bg-card px-3 py-1 md:sticky md:top-0 md:px-3.5">
                  <p className={cn("text-tf-meta font-semibold", banda.tone)}>
                    {banda.label} · {filas.length}
                  </p>
                  {banda.hint && (
                    <p className="text-tf-micro text-muted-foreground">{banda.hint}</p>
                  )}
                </div>
                {filas.map(({ item, index }, posicion) => (
                  <AgendaFila
                    key={claveDe(item)}
                    item={item}
                    activa={index === activeIndex}
                    anidada={anidadas[posicion]}
                    rowPad={rowPad}
                    onSeleccionar={() => agenda.setSelected(index)}
                    acciones={{
                      onAbrir: () => agenda.abrir(item),
                      onSeguir: () => void agenda.seguir(item),
                      onDescartar: () => agenda.descartar(item),
                      onCompletar: () => agenda.completarTarea(item),
                      onEditarAccion: () => {
                        agenda.setSelected(index);
                        agenda.editarAccion(item);
                      },
                      onVerRenovacion: agenda.verRenovacion,
                      onRetirar: () => agenda.pedirRetirada(item),
                      onApuntarAccion: (accion, alGuardar) =>
                        agenda.apuntarAccion(item, accion, alGuardar),
                      apuntando: agenda.apuntando,
                    }}
                  />
                ))}
              </React.Fragment>
            );
          })
        )}
      </div>
    </section>
  );
}
