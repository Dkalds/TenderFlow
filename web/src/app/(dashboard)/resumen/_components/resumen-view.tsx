"use client";

import { useCallback, useRef } from "react";
import {
  ScrollEdgeDelProveedor,
  ScrollEdgeProvider,
  ScrollEdgeSentinel,
} from "@/components/layout/scroll-edge";
import { BarraAsistente } from "@/components/asistente/barra-asistente";
import { Panel } from "@/components/console/panel";
import { CONSOLE_SPACES } from "@/lib/console-spaces";
import { TuDia } from "./tu-dia";
import { DesdeUltimaVisita } from "./desde-ultima-visita";
import { PrimerosPasos } from "./primeros-pasos";
import { AtencionCards, ColaCierreHoy } from "./atencion-cards";
import { PublicacionesPanel } from "./publicaciones-panel";
import { UltimasPublicaciones } from "./ultimas-publicaciones";
import { AtajosAnalisis } from "./atajos-analisis";
import { ParaTi } from "./para-ti";
import { TusOportunidades } from "./tus-oportunidades";

/**
 * Resumen — la entrada del producto. Es la parte cliente de la pantalla; el
 * `page.tsx` de servidor la envuelve con el prefetch de sus primeros datos.
 *
 * La página va **de dentro hacia fuera**, en una rejilla de cuatro filas
 * (rediseño del 2026-11-16, que sustituye al Resumen compacto del
 * 2026-10-31). Cada bloque es un panel con su título dentro:
 *
 * 1. **Lo de hoy.** «Tu día» (`GET /pursuits/agenda`: Go/No-Go, sin próxima
 *    acción y la semana por días) a cinco doceavos y «Cierran en 48 h» (la
 *    cola de cierre con su recuento) a siete.
 * 2. **Lo tuyo.** «Para ti», lo primero de la bandeja del Radar, y «Tus
 *    oportunidades», el tablero de la organización por fases
 *    (`GET /pursuits/metrics`).
 * 3. **El mercado.** «Mercado hoy», con el ámbito de la barra: la tira de
 *    cifras y las publicaciones del periodo debajo; al lado, «Lo que sigues»
 *    (F5.4).
 * 4. **La lista.** Últimas publicaciones a todo el ancho.
 *
 * La composición por estado, el mapa por comunidad y los movimientos del
 * mercado salieron del Resumen en ese rediseño. El análisis del ámbito sigue en
 * Mercado, a un clic desde los atajos de «Mercado hoy»; el feed de movimientos
 * (`GET /eventos`) se quedó sin pantalla.
 *
 * «Primeros pasos» va al pie, salvo en una cuenta sin ningún paso hecho, donde
 * sube arriba del todo (`posicionDe`).
 *
 * Desde `xl` cada fila es una rejilla; por debajo las columnas se apilan en
 * ese mismo orden, así que en un teléfono la lectura sigue siendo lo de hoy,
 * lo tuyo y después el mercado.
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

            {/* Fila 1: lo de hoy. Las dos se estiran al mismo alto: la cola
                de cierre crece con filas en vez de dejar un hueco. */}
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
              <TuDia />
              <ColaCierreHoy />
            </div>

            {/* Fila 2: lo tuyo, la bandeja del Radar y el tablero. */}
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
              <ParaTi />
              <TusOportunidades />
            </div>

            {/* Fila 3: el mercado con el ámbito de la barra y lo que cambió en
                lo que sigues. */}
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,8fr)_minmax(0,4fr)]">
              <Panel className="flex min-w-0 flex-col gap-4">
                <section aria-labelledby="resumen-mercado" className="contents">
                  {/* Como un `PanelTitle`, pero los atajos bajan de línea: en el
                      hueco de acciones no se parten, y a 375 px sacaban
                      «Órganos» por la derecha y la página hacía scroll
                      horizontal. */}
                  <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
                    <h2 id="resumen-mercado" className="flex-none text-tf-body font-semibold">
                      Mercado hoy
                    </h2>
                    <span className="min-w-0 text-tf-meta text-muted-foreground">con el ámbito de la barra</span>
                    <AtajosAnalisis className="sm:ml-auto" />
                  </div>
                  <AtencionCards />
                  <PublicacionesPanel />
                </section>
              </Panel>
              <DesdeUltimaVisita />
            </div>

            {/* Fila 4: la lista. */}
            <UltimasPublicaciones />

            <PrimerosPasos posicion="abajo" onDescartar={recogerFoco} />
          </div>
        </div>
      </div>
    </ScrollEdgeProvider>
  );
}
