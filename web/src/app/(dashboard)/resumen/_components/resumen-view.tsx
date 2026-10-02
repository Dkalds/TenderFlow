"use client";

import { useCallback, useRef } from "react";
import {
  ScrollEdgeDelProveedor,
  ScrollEdgeProvider,
  ScrollEdgeSentinel,
} from "@/components/layout/scroll-edge";
import { CopilotBar } from "@/components/copilot-panel";
import { CONSOLE_SPACES } from "@/lib/console-spaces";
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
 *    para no desplazar la tesis de la pantalla, salvo en una cuenta sin ningún
 *    paso hecho: ahí sube arriba del todo, porque lo que había encima eran
 *    ceros y listas vacías y la banda era lo único accionable
 *    (`primeros-pasos.tsx`, `posicionDe`).
 * 2. **Mercado abierto** — lo que exige mirar hoy en el corpus, con el destino
 *    real de cada tarjeta en su pie. La banda no reparte el espacio a partes
 *    iguales: lo que tiene plazo (la cola de cierre) ocupa dos tercios y trae
 *    sus primeras filas, para que lo urgente se resuelva sin salir. «Nuevas»
 *    cuenta desde tu última visita: es la única idea de «nuevo» del mercado
 *    en la pantalla (`_hooks/use-novedades.ts`).
 * 3. **Contexto de mercado** — tres cifras del ámbito: activas, publicadas y
 *    importe de los últimos 30 días. Aquí baja «Activas»: describe el ámbito,
 *    no pide nada para hoy. Fue una tira de siete magnitudes más otra de seis
 *    indicadores de competencia, medio globales; se retiraron (2026-10) porque
 *    son la radiografía del mercado que esta pantalla dejó de abrir, y viven en
 *    Mercado y Competencia.
 * 4. **Composición** — por estado; pulsar un estado filtra.
 * 5. **Publicaciones** — los cortes del periodo y la tabla, con el tope del
 *    endpoint declarado y las filas nuevas desde tu última visita marcadas.
 * 6. **Movimientos** — qué contratos se han movido en la ventana.
 * 7. **Análisis completo** — los atajos, que arrastran el ámbito.
 *
 * Todas aplican el ámbito entero de la barra de filtros, salvo las personales
 * (0 y 1, que son de lo que sigues y de tu organización).
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
          <CopilotBar className="mb-4 max-w-[720px]" />

          <PrimerosPasos posicion="arriba" onDescartar={recogerFoco} />
          <DesdeUltimaVisita />
          <TuDia />
          <PrimerosPasos posicion="abajo" onDescartar={recogerFoco} />
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
