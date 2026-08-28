"use client";

import { useCallback, useRef } from "react";
import { ExportPopover } from "@/components/export-popover";
import { CopilotBar } from "@/components/copilot-panel";
import { TuDia } from "./_components/tu-dia";
import { PrimerosPasos } from "./_components/primeros-pasos";
import { AtencionCards } from "./_components/atencion-cards";
import { ContextoStrip } from "./_components/contexto-strip";
import { ComposicionPanel } from "./_components/composicion-panel";
import { TimelineSection } from "./_components/timeline-section";
import { EventosFeed } from "./_components/eventos-feed";
import { AtajosAnalisis } from "./_components/atajos-analisis";

/**
 * Resumen — la entrada del producto.
 *
 * El orden de la pantalla es su tesis, y la anterior tenía la tesis cambiada:
 * abría con «Total licitaciones» y «Órganos únicos» —una radiografía del
 * mercado español— en un producto cuyo usuario entra para saber qué tiene que
 * hacer hoy. Todo lo personal (pursuits con plazo, Go/No-go sin decidir,
 * señales de sus reglas sin triar) vivía en Mi Pipeline y la entrada no daba
 * ninguna pista de que existiera. Ahora la página va **de dentro hacia fuera**:
 *
 * 1. **Tu día** — compromisos de tu organización (`GET /pursuits/agenda`).
 * 1b. **Primeros pasos** — sólo mientras al usuario le falte configurar algo que
 *    el producto necesita para hablar de su negocio. Va **debajo** de «Tu día»
 *    a propósito: no desplaza la tesis de la pantalla, y en una cuenta nueva
 *    «Tu día» ocupa una línea vacía, así que cae igualmente en la primera
 *    pantalla, justo donde explica por qué esa línea está vacía.
 * 2. **Mercado abierto** — lo que exige mirar hoy en el corpus, con el destino
 *    real de cada tarjeta en su pie.
 * 3. **Contexto y salud competitiva** — la foto del ámbito y los indicadores de
 *    concentración, con los deltas entre meses cerrados.
 * 4. **Composición** — por estado y por órgano; pulsar un estado filtra.
 * 5. **Publicaciones** — la nube y la tabla, con el tope del endpoint declarado.
 * 6. **Movimientos** — qué contratos se han movido en la ventana.
 * 7. **Análisis completo** — los atajos, que arrastran el ámbito.
 *
 * Cada banda pide su propio dato y pinta su propio error. Antes un fallo de
 * `/analytics/overview` dejaba la pantalla entera en una tarjeta de error, con
 * lo que caía también lo que sí había cargado — y en la pantalla de entrada
 * eso se lee como «la aplicación está rota», no como «un panel no responde».
 */
export default function ResumenPage() {
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

  return (
    <div className="flex h-[calc(100vh-52px)] min-h-0 flex-col">
      <header className="border-border/60 flex h-11 flex-none items-center gap-2.5 border-b px-4">
        <h1 className="font-display text-[13px] font-semibold">Resumen</h1>
        <span className="text-muted-foreground hidden truncate text-[11.5px] lg:inline">
          qué tienes que hacer hoy y qué se ha movido en el mercado
        </span>
        <div className="flex-1" />
        <ExportPopover className="[&>button]:h-7 [&>button]:px-2.5 [&>button]:py-0 [&>button]:text-xs" />
      </header>

      <div
        ref={contenidoRef}
        tabIndex={-1}
        className="min-h-0 flex-1 overflow-y-auto px-4 pt-4 pb-6 outline-none"
      >
        <CopilotBar className="mb-4 max-w-[720px]" />

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
  );
}
