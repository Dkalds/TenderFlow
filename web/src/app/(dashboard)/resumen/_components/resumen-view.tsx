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
import { AtencionCards, ColaCierreHoy } from "./atencion-cards";
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
 * compacta de cuatro filas en vez de diez bandas apiladas (unos 3.400 px a
 * 1920 de ancho, que pedían tres pantallas de scroll para ver la foto entera).
 * Es el diseño aprobado del Resumen compacto:
 *
 * 1. **Dos tiras de cifras, lado a lado.** «Tu día» (`GET /pursuits/agenda`,
 *    los cuatro contadores; la semana en carriles se despliega bajo demanda) y
 *    «Mercado hoy», con el ámbito de la barra: cierran en 48 h, grandes en
 *    plazo, nuevas desde tu última visita y activas. Con el mismo peso: lo
 *    tuyo y el mercado se leen de un vistazo, sin scroll.
 * 2. **Qué cierra y qué cambió.** La cola de cierre de 48 h a siete doceavos
 *    y «Desde tu última visita» (F5.4) al lado; la cola se estira hasta el
 *    alto de la banda con más filas en vez de dejar un hueco.
 * 3. **El periodo y la foto del ámbito.** Las publicaciones del mes con sus
 *    cifras, la composición por estado y el mapa por comunidad, que filtran al
 *    pulsarlos.
 * 4. **Las listas.** Últimas publicaciones a dos tercios y los movimientos
 *    del mercado en el tercio restante.
 *
 * «Primeros pasos» va al pie, salvo en una cuenta sin ningún paso hecho, donde
 * sube arriba del todo (`posicionDe`).
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

            {/* Fila 1: las dos tiras de cifras. Arriba y no estiradas: el aviso
                de «Tu día» alarga su columna y la tira del mercado no tiene con
                qué llenar ese alto. */}
            <div className="grid grid-cols-1 items-start gap-3 xl:grid-cols-2">
              <TuDia />
              <section aria-labelledby="resumen-mercado" className="min-w-0">
                {/* Como el `PanelTitle` de «Tu día», pero los atajos bajan de
                    línea: en el hueco de acciones no se parten, y a 375 px
                    sacaban «Órganos» por la derecha y la página hacía scroll
                    horizontal. */}
                <div className="mb-2.5 flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
                  <h2 id="resumen-mercado" className="flex-none text-tf-body font-semibold">
                    Mercado hoy
                  </h2>
                  <span className="min-w-0 text-tf-meta text-muted-foreground">con el ámbito de la barra</span>
                  <AtajosAnalisis className="sm:ml-auto" />
                </div>
                <AtencionCards />
              </section>
            </div>

            {/* Fila 2: qué cierra y qué cambió. Las dos se estiran al mismo
                alto: la cola de cierre crece con filas en vez de dejar un
                hueco. */}
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
              <ColaCierreHoy />
              <DesdeUltimaVisita />
            </div>

            {/* Fila 3: el periodo y la foto del ámbito. */}
            <section
              aria-labelledby="resumen-periodo"
              className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-[minmax(0,5fr)_minmax(0,3fr)_minmax(0,4fr)]"
            >
              <h2 id="resumen-periodo" className="sr-only">
                El periodo y el ámbito
              </h2>
              <div className="flex min-w-0 flex-col lg:col-span-2 xl:col-span-1">
                <PublicacionesPanel />
              </div>
              <ComposicionPanel />
              <ComunidadesPanel />
            </section>

            {/* Fila 4: las listas. */}
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,8fr)_minmax(0,4fr)]">
              <UltimasPublicaciones />
              <EventosFeed />
            </div>

            <PrimerosPasos posicion="abajo" onDescartar={recogerFoco} />
          </div>
        </div>
      </div>
    </ScrollEdgeProvider>
  );
}
