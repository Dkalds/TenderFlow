"use client";

import { useCallback, useRef } from "react";
import {
  ScrollEdgeDelProveedor,
  ScrollEdgeProvider,
  ScrollEdgeSentinel,
} from "@/components/layout/scroll-edge";
import { BarraAsistente } from "@/components/asistente/barra-asistente";
import { CONSOLE_SPACES } from "@/lib/console-spaces";
import { TuDia } from "./tu-dia";
import { DesdeUltimaVisita } from "./desde-ultima-visita";
import { PrimerosPasos } from "./primeros-pasos";
import { AtencionCards } from "./atencion-cards";
import { ContextoStrip } from "./contexto-strip";
import { PublicacionesPanel } from "./publicaciones-panel";
import { UltimasPublicaciones } from "./ultimas-publicaciones";
import { EventosFeed } from "./eventos-feed";
import { AtajosAnalisis } from "./atajos-analisis";
import { ComposicionPanel } from "./composicion-panel";
import { ComunidadesPanel } from "./comunidades-panel";

/**
 * Resumen — la entrada del producto. Es la parte cliente de la pantalla; el
 * `page.tsx` de servidor la envuelve con el prefetch de sus primeros datos.
 *
 * La página va **de dentro hacia fuera**, y desde 2026-10-31 en una rejilla
 * compacta en vez de diez bandas apiladas (unos 3.400 px a 1920 de ancho, que
 * pedían tres pantallas de scroll para ver la foto entera):
 *
 * 1. **Arriba, lo tuyo junto al mercado de hoy.** A la izquierda «Tu día»
 *    (`GET /pursuits/agenda`, los cuatro contadores; la semana en carriles se
 *    despliega bajo demanda) y «Desde tu última visita» (F5.4). A la derecha,
 *    con su rótulo «Mercado» y los atajos al análisis completo —desde ahí todo
 *    aplica el ámbito de la barra—, «Grandes en plazo», «Nuevas» y la cola de
 *    cierre de 48 h, que se estira hasta el alto de la columna de al lado.
 *    «Primeros pasos» va al pie de la columna izquierda, salvo en una cuenta
 *    sin ningún paso hecho, donde sube arriba del todo (`posicionDe`).
 * 2. **El periodo y la foto del ámbito, en una fila.** La tira de cifras
 *    (activas, publicadas e importe de 30 días) sobre el gráfico de
 *    publicaciones, y al lado la composición por estado y el mapa por
 *    comunidad, que filtran al pulsarlos.
 * 3. **Las listas, en otra.** Últimas publicaciones a dos tercios y los
 *    movimientos del mercado en el tercio restante.
 *
 * Desde `xl` cada fila es una rejilla; por debajo las columnas se apilan en
 * ese mismo orden, así que en un teléfono la lectura sigue siendo lo tuyo,
 * lo de hoy y después el resto.
 *
 * Cada panel pide su propio dato y pinta su propio error. Antes un fallo de
 * `/analytics/overview` dejaba la pantalla entera en una tarjeta de error, con
 * lo que caía también lo que sí había cargado — y en la pantalla de entrada
 * eso se lee como «la aplicación está rota», no como «un panel no responde».
 */
/** Qué trabajo resuelve la pantalla: la misma frase del rail y de la paleta. */
const DESCRIPCION = CONSOLE_SPACES.find((space) => space.key === "resumen")?.description;

export function ResumenView() {
  const contenidoRef = useRef<HTMLDivElement>(null);

  /**
   * Al ocultar «Primeros pasos» la sección se desmonta con el foco dentro, y un
   * foco huérfano manda al lector de pantalla al principio del documento. Se
   * recoge en el contenedor de la pantalla, sin arrastrar el scroll: el usuario
   * seguía mirando donde estaba.
   */
  const recogerFoco = useCallback(() => {
    contenidoRef.current?.focus({ preventScroll: true });
  }, []);

  // Borde de scroll y no `border-b` fijo (apple-design §12): quien scrollea es
  // el cuerpo de la pantalla, no `#main-content`, así que lleva su propio
  // proveedor y en el tope no hay línea.
  //
  // La cabecera es la de `SpaceShell`: título en la display a 15 px, la
  // descripción del espacio en tono meta y el asistente. Sin «Exportar»: la barra de ámbito
  // ya lleva «Exportar ámbito», con el mismo endpoint y los mismos filtros, y
  // dos botones iguales a un palmo no se distinguen.
  return (
    <ScrollEdgeProvider>
      <div className="flex h-full min-h-0 flex-col">
        {/* El asistente sube a la cabecera: era una banda propia de 60 px
            antes de cualquier dato. */}
        <header className="flex min-h-11 flex-none flex-wrap items-center gap-x-2.5 gap-y-2 px-4 py-1.5">
          <h1 className="flex-none font-display text-tf-lede font-semibold">Resumen</h1>
          {DESCRIPCION && (
            <span className="hidden min-w-0 truncate text-tf-meta text-muted-foreground lg:inline">{DESCRIPCION}</span>
          )}
          <BarraAsistente className="h-9 w-full sm:ml-auto sm:w-[380px]" />
        </header>
        <ScrollEdgeDelProveedor />

        {/* `relative`, como el cuerpo de `SpaceShell`: el `sr-only` de cada fila
            («Oportunidad · Plazo de presentación:») es absoluto y sin él colgaba
            del viewport; a 375×812 el último estiraba el documento 29 px. */}
        <div
          ref={contenidoRef}
          tabIndex={-1}
          className="relative min-h-0 flex-1 overflow-y-auto px-4 pt-3 pb-6 outline-none"
        >
          <ScrollEdgeSentinel />
          <div className="flex flex-col gap-3">
            <PrimerosPasos posicion="arriba" onDescartar={recogerFoco} />

            {/* Fila 1: lo tuyo a la izquierda y el mercado de hoy a la derecha.
                Las dos columnas se estiran al mismo alto: la cola de cierre
                crece con filas en vez de dejar un hueco. */}
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
              <div className="flex min-w-0 flex-col gap-3">
                <TuDia />
                <DesdeUltimaVisita />
                <PrimerosPasos posicion="abajo" onDescartar={recogerFoco} />
              </div>

              <section aria-labelledby="resumen-mercado" className="flex min-w-0 flex-col">
                <div className="mb-2.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <h2 id="resumen-mercado" className="flex-none font-display text-tf-lede font-semibold">
                    Mercado
                  </h2>
                  <span className="min-w-0 text-tf-meta text-muted-foreground">con el ámbito de la barra</span>
                  <AtajosAnalisis className="sm:ml-auto" />
                </div>
                <AtencionCards className="flex-1" />
              </section>
            </div>

            {/* Fila 2: el periodo y la foto del ámbito. La tira en cifras va
                encima de lo que dibuja; la composición y el mapa, al lado. */}
            <section
              aria-labelledby="resumen-periodo"
              className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-[minmax(0,5fr)_minmax(0,3fr)_minmax(0,4fr)]"
            >
              <h2 id="resumen-periodo" className="sr-only">
                El periodo y el ámbito
              </h2>
              <div className="flex min-w-0 flex-col gap-3 lg:col-span-2 xl:col-span-1">
                <ContextoStrip />
                <PublicacionesPanel />
              </div>
              <ComposicionPanel />
              <ComunidadesPanel />
            </section>

            {/* Fila 3: las listas. */}
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,8fr)_minmax(0,4fr)]">
              <UltimasPublicaciones />
              <EventosFeed />
            </div>
          </div>
        </div>
      </div>
    </ScrollEdgeProvider>
  );
}
