"use client";

import { useCallback, useRef } from "react";
import { ExportPopover } from "@/components/export-popover";
import {
  ScrollEdgeDelProveedor,
  ScrollEdgeProvider,
  ScrollEdgeSentinel,
} from "@/components/layout/scroll-edge";
import { CopilotBar } from "@/components/copilot-panel";
import { TuDia } from "./tu-dia";
import { DesdeUltimaVisita } from "./desde-ultima-visita";
import { PrimerosPasos } from "./primeros-pasos";
import { AtencionCards } from "./atencion-cards";
import { ContextoStrip } from "./contexto-strip";
import { ComposicionPanel } from "./composicion-panel";
import { TimelineSection } from "./timeline-section";
import { EventosFeed } from "./eventos-feed";
import { AtajosAnalisis } from "./atajos-analisis";

/**
 * Resumen — la entrada del producto. Es la parte cliente de la pantalla; el
 * `page.tsx` de servidor la envuelve con el prefetch de sus primeros datos.
 *
 * El orden de la pantalla es su tesis, y la anterior tenía la tesis cambiada:
 * abría con «Total licitaciones» y «Órganos únicos» —una radiografía del
 * mercado español— en un producto cuyo usuario entra para saber qué tiene que
 * hacer hoy. Todo lo personal (pursuits con plazo, Go/No-go sin decidir,
 * señales de sus reglas sin triar) vivía en Mi Pipeline y la entrada no daba
 * ninguna pista de que existiera. Ahora la página va **de dentro hacia fuera**:
 *
 * 0. **Desde tu última visita** (F5.4) — qué se movió en lo que sigues y en el
 *    pipeline del equipo (`GET /analytics/resumen/desde-mi-ultima-visita`).
 *    Abre la pantalla porque es la pregunta de quien entra una vez al día, y
 *    con cero cambios lo dice en una línea en vez de desaparecer.
 * 1. **Tu día** — compromisos de tu organización (`GET /pursuits/agenda`).
 * 1b. **Primeros pasos** — sólo mientras al usuario le falte configurar algo que
 *    el producto necesita para hablar de su negocio. Va **debajo** de «Tu día»
 *    a propósito: no desplaza la tesis de la pantalla, y en una cuenta nueva
 *    «Tu día» ocupa una línea vacía, así que cae igualmente en la primera
 *    pantalla, justo donde explica por qué esa línea está vacía.
 * 2. **Mercado abierto** — lo que exige mirar hoy en el corpus, con el destino
 *    real de cada tarjeta en su pie. La banda no reparte el espacio a partes
 *    iguales: lo que tiene plazo (la cola de cierre) ocupa dos tercios y trae
 *    sus primeras filas, para que lo urgente se resuelva sin salir.
 * 3. **Contexto y salud competitiva** — la foto del ámbito y los indicadores de
 *    concentración, con los deltas entre meses cerrados. Aquí baja «Activas»:
 *    describe el ámbito, no pide nada para hoy.
 * 4. **Composición** — por estado y por órgano; pulsar un estado filtra.
 * 5. **Publicaciones** — novedades, los cortes del periodo y la tabla, con el
 *    tope del endpoint declarado y las filas nuevas marcadas.
 * 6. **Movimientos** — qué contratos se han movido en la ventana.
 * 7. **Análisis completo** — los atajos, que arrastran el ámbito.
 *
 * Cada banda pide su propio dato y pinta su propio error. Antes un fallo de
 * `/analytics/overview` dejaba la pantalla entera en una tarjeta de error, con
 * lo que caía también lo que sí había cargado — y en la pantalla de entrada
 * eso se lee como «la aplicación está rota», no como «un panel no responde».
 */
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
  return (
    <ScrollEdgeProvider>
      <div className="flex h-[calc(100vh-52px)] min-h-0 flex-col">
        <header className="flex h-11 flex-none items-center gap-2.5 px-4">
          <h1 className="font-display text-[13px] font-semibold">Resumen</h1>
          <span className="text-muted-foreground hidden truncate text-[11.5px] lg:inline">
            qué tienes que hacer hoy y qué se ha movido en el mercado
          </span>
          <div className="flex-1" />
          <ExportPopover className="[&>button]:h-7 [&>button]:px-2.5 [&>button]:py-0 [&>button]:text-xs" />
        </header>
        <ScrollEdgeDelProveedor />

        <div
          ref={contenidoRef}
          tabIndex={-1}
          className="min-h-0 flex-1 overflow-y-auto px-4 pt-4 pb-6 outline-none"
        >
          <ScrollEdgeSentinel />
          <CopilotBar className="mb-4 max-w-[720px]" />

          <DesdeUltimaVisita />
          <TuDia />
          <PrimerosPasos onDescartar={recogerFoco} />
          <AtencionCards />
          <ContextoStrip />
          <ComposicionPanel />
          <TimelineSection />
          <EventosFeed />
          <AtajosAnalisis />
        </div>
      </div>
    </ScrollEdgeProvider>
  );
}
