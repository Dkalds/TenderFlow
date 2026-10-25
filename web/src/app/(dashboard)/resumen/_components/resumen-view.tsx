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
 * El orden de la pantalla es su tesis, y la anterior tenía la tesis cambiada:
 * abría con «Total licitaciones» y «Órganos únicos» —una radiografía del
 * mercado español— en un producto cuyo usuario entra para saber qué tiene que
 * hacer hoy. Ahora la página va **de dentro hacia fuera**, en dos zonas:
 *
 * **Lo tuyo** (sin cabecera de zona: es el principio de la página, y sus dos
 * bandas no aplican el ámbito de la barra):
 *
 * 1. **Tu día** — compromisos de tu organización (`GET /pursuits/agenda`).
 *    Abre la pantalla porque es lo que la descripción del espacio promete
 *    primero, «qué tienes que hacer hoy».
 * 2. **Desde tu última visita** (F5.4) — qué se movió en lo que sigues y en el
 *    pipeline del equipo (`GET /analytics/resumen/desde-mi-ultima-visita`).
 *    Con cero cambios lo dice en una línea en vez de desaparecer.
 * 3. **Primeros pasos** — sólo mientras al usuario le falte configurar algo que
 *    el producto necesita para hablar de su negocio. Va al cierre de la zona
 *    para no desplazar su tesis, salvo en una cuenta sin ningún paso hecho:
 *    ahí sube arriba del todo, porque lo que había encima eran ceros y listas
 *    vacías y la banda era lo único accionable (`primeros-pasos.tsx`,
 *    `posicionDe`).
 *
 * **Mercado** (con cabecera, filete encima y los atajos al análisis completo,
 * porque desde ahí todo aplica el ámbito entero de la barra de filtros):
 *
 * 4. **Abierto hoy** — la cola de cierre a dos tercios con sus primeras filas
 *    y, al lado, «Grandes en plazo» y «Nuevas» desde tu última visita
 *    (`_hooks/use-novedades.ts`).
 * 5. **El periodo** — las tres cifras del ámbito (activas, publicadas e
 *    importe de 30 días) y, debajo, el ritmo de publicaciones junto a los
 *    movimientos del mercado: la tira es el resumen en cifras de lo que los
 *    dos paneles dibujan.
 * 6. **Últimas publicaciones** — la tabla, con el tope del endpoint declarado,
 *    el origen de cada expediente y las filas nuevas desde tu última visita.
 * 7. **Foto del ámbito** — la composición por estado y el reparto por
 *    comunidad, que filtran al pulsarlos. Van al final: describen el ámbito,
 *    no piden nada para hoy.
 *
 * **Por qué zonas** (2026-10-25): la pantalla tenía diez bandas apiladas con
 * el mismo rótulo de 13 px sobre el mismo panel, unos 3.400 px a 1920 de
 * ancho, y al entrecerrar los ojos nada mandaba. Lo personal y lo del ámbito
 * se leían como una sola lista; ahora los separa un salto de ritmo —holgura
 * entre zonas, apretado dentro— y el mercado tiene un rótulo que dice desde
 * dónde empieza a contar la barra de filtros.
 *
 * Cada banda pide su propio dato y pinta su propio error. Antes un fallo de
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
  // La cabecera es la de `SpaceShell`: título en la display a 15 px y la
  // descripción del espacio en tono meta. Sin «Exportar»: la barra de ámbito
  // ya lleva «Exportar ámbito», con el mismo endpoint y los mismos filtros, y
  // dos botones iguales a un palmo no se distinguen.
  return (
    <ScrollEdgeProvider>
      <div className="flex h-full min-h-0 flex-col">
        <header className="flex h-11 flex-none items-center gap-2.5 px-4">
          <h1 className="flex-none font-display text-tf-lede font-semibold">Resumen</h1>
          {DESCRIPCION && (
            <span className="hidden truncate text-tf-meta text-muted-foreground lg:inline">{DESCRIPCION}</span>
          )}
        </header>
        <ScrollEdgeDelProveedor />

        {/* `relative`, como el cuerpo de `SpaceShell`: el `sr-only` de cada fila
            («Oportunidad · Plazo de presentación:») es absoluto y sin él colgaba
            del viewport; a 375×812 el último estiraba el documento 29 px. */}
        <div
          ref={contenidoRef}
          tabIndex={-1}
          className="relative min-h-0 flex-1 overflow-y-auto px-4 pt-4 pb-6 outline-none"
        >
          <ScrollEdgeSentinel />
          <BarraAsistente className="mb-5 max-w-[720px]" />

          {/* Lo tuyo: apretado dentro (gap 5), y las bandas no aplican el ámbito. */}
          <div className="flex flex-col gap-5">
            <PrimerosPasos posicion="arriba" onDescartar={recogerFoco} />
            <TuDia />
            <DesdeUltimaVisita />
            <PrimerosPasos posicion="abajo" onDescartar={recogerFoco} />
          </div>

          {/* El mercado: el salto de ritmo (mt-9 y el filete) es lo que separa
              las dos zonas; dentro, el mismo gap 5 que arriba. */}
          <section aria-labelledby="resumen-mercado" className="mt-9 border-t border-divider pt-4">
            <div className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-2">
              <h2 id="resumen-mercado" className="flex-none font-display text-tf-lede font-semibold">
                Mercado
              </h2>
              <span className="min-w-0 text-tf-meta text-muted-foreground">con el ámbito de la barra</span>
              <AtajosAnalisis className="sm:ml-auto" />
            </div>

            <div className="flex flex-col gap-5">
              <AtencionCards />

              {/* El periodo: la tira en cifras y, debajo, lo que dibuja. Las dos
                  columnas se estiran al mismo alto: el gráfico crece hasta el
                  de los movimientos en vez de dejar un hueco debajo. */}
              <section aria-labelledby="resumen-periodo" className="flex flex-col gap-2.5">
                <h3 id="resumen-periodo" className="sr-only">
                  Últimos 30 días
                </h3>
                <ContextoStrip />
                <div className="grid grid-cols-1 gap-2.5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
                  <PublicacionesPanel />
                  <EventosFeed />
                </div>
              </section>

              <UltimasPublicaciones />

              {/* La foto del ámbito: los dos cortes que filtran al pulsarlos,
                  lado a lado desde `xl` y estirados al mismo alto. */}
              <div className="grid grid-cols-1 gap-2.5 xl:grid-cols-2">
                <ComposicionPanel />
                <ComunidadesPanel />
              </div>
            </div>
          </section>
        </div>
      </div>
    </ScrollEdgeProvider>
  );
}
