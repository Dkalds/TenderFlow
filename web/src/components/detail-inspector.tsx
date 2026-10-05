"use client";

import * as React from "react";
import { Maximize2, X } from "lucide-react";
import { LicitacionAI } from "@/components/licitacion-ai";
import { CompetenciaEsperadaBlock } from "@/components/competencia-esperada";
import { TenderFactSheetPanel } from "@/components/pursuits/tender-fact-sheet";
import { DocumentosBlock } from "@/components/documentos-block";
import { TecnologiasBlock } from "@/components/tecnologias-block";
import { PrediccionBajaBlock } from "@/components/prediccion-baja";
import { SimuladorPuntuacion } from "@/components/pliego/simulador-puntuacion";
import { GuionOfertaPanel } from "@/components/pliego/guion-oferta";
import { useResoluciones } from "@/components/resoluciones-block";
import { PanelTabs, SectionTitle, panelDePestana } from "@/components/console/panel";
import { FichaAcciones, FichaAvisos, FichaEstado, FichaOrgano } from "@/components/ficha/ficha-cabecera";
import { FichaCifras } from "@/components/ficha/ficha-cifras";
import { FichaCampos } from "@/components/ficha/ficha-campos";
import {
  FichaDescripcion,
  FichaEventos,
  FichaFuente,
  FichaPuntuacion,
  FichaRecursos,
} from "@/components/ficha/ficha-secciones";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { LicitacionDetail } from "@/lib/licitacion-detail";

/**
 * Inspector de la licitación — la ficha en el mismo plano que la tabla.
 *
 * Lo que decide si mirar una licitación va arriba y sin pestañas: estado,
 * título, órgano y lugar, las cifras (importe, fecha límite, puntuación y baja
 * esperada) y los avisos del score. Antes la cabecera solo enseñaba el importe
 * y la fecha límite vivía en la rejilla de campos, por debajo de cinco bloques
 * de la pestaña Resumen.
 *
 * Debajo, cinco pestañas con lo que antes se apilaba en cuatro:
 *
 * - **Resumen**: los campos, el desglose de la puntuación, la descripción
 *   (recortada), las tecnologías, el enlace al portal y los eventos.
 * - **Competencia**: competencia esperada, baja esperada y simulador de
 *   puntuación, que antes alargaban el Resumen.
 * - **Pliegos**: documentos, ficha estructurada del pliego (lotes, criterios,
 *   ANS, certificaciones citables) y el guion de oferta que se apoya en ella.
 * - **IA**: el asistente (resumen y «Preguntar»).
 * - **Recursos**: resoluciones del TACRC.
 *
 * Todo el contenido se desplaza en una sola caja y las pestañas se quedan
 * pegadas arriba: con la cabecera fija, en un portátil de 768 px de alto el
 * contenido de la pestaña se quedaba con un tercio de la altura.
 *
 * Con `onExpandir`, un botón abre la ficha completa (todas las secciones a la
 * vez, a pantalla entera).
 */

type TabKey = "resumen" | "competencia" | "pliegos" | "ia" | "recursos";

const TABS: { key: TabKey; label: string }[] = [
  { key: "resumen", label: "Resumen" },
  { key: "competencia", label: "Competencia" },
  { key: "pliegos", label: "Pliegos" },
  { key: "ia", label: "IA" },
  { key: "recursos", label: "Recursos" },
];

export function DetailInspector({
  licitacion: l,
  onClose,
  onExpandir,
  className,
}: {
  licitacion: LicitacionDetail;
  onClose: () => void;
  onExpandir?: () => void;
  className?: string;
}) {
  const [tab, setTab] = React.useState<TabKey>("resumen");
  // Bump para activar la pestaña «Preguntar» del asistente desde la cabecera.
  const [askSignal, setAskSignal] = React.useState(0);
  const { data: resoluciones } = useResoluciones(l.id_externo);
  const idPestanas = React.useId();

  // Al cambiar de licitación se vuelve a Resumen: dejar abierta la pestaña de
  // Pliegos de la fila anterior invita a leer el pliego equivocado. /detalle ya
  // monta una ficha por expediente (`key`); esto cubre a quien la reutilice
  // sin `key`. Se deriva durante el render (patrón recomendado por React para
  // un valor externo) en vez de con un efecto, que provocaría un render en
  // cascada.
  const [prevId, setPrevId] = React.useState(l.id_externo);
  if (prevId !== l.id_externo) {
    setPrevId(l.id_externo);
    setTab("resumen");
  }

  const preguntar = () => {
    setTab("ia");
    setAskSignal((key) => key + 1);
  };

  const resolucionesCount = resoluciones?.items?.length ?? 0;
  // Sólo se cuenta lo que se puede contar sin pedir un dato extra. Un contador
  // inventado en una pestaña es peor que ningún contador.
  const pestanas = TABS.map((item) =>
    item.key === "recursos" && resolucionesCount > 0 ? { ...item, badge: resolucionesCount } : item,
  );

  return (
    <aside aria-label="Ficha de la licitación" className={cn("flex min-h-0 flex-1 flex-col bg-card", className)}>
      <div className="flex flex-none items-center gap-2 border-b border-border/60 px-4 py-2">
        <FichaEstado licitacion={l} className="flex-1" />
        {onExpandir && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                onClick={onExpandir}
                aria-label="Abrir la ficha completa"
                className="text-muted-foreground"
              >
                <Maximize2 aria-hidden="true" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Ficha completa, a pantalla entera</TooltipContent>
          </Tooltip>
        )}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={onClose}
              aria-label="Cerrar ficha"
              className="text-muted-foreground"
            >
              <X aria-hidden="true" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Cerrar · Esc</TooltipContent>
        </Tooltip>
      </div>

      {/* Una sola caja con scroll, `relative` para que los `sr-only` y los
          absolutos de dentro no tomen el viewport como bloque contenedor
          (docs/UX_AUDIT.md, «scroll fantasma»). Las pestañas van `sticky`. */}
      <div className="relative min-h-0 flex-1 overflow-y-auto">
        <div className="flex flex-col gap-3 px-4 pb-3 pt-3.5">
          <div className="flex flex-col gap-1.5">
            <h2 className="font-display text-tf-lede font-semibold text-pretty">
              {l.titulo ?? l.id_externo}
            </h2>
            <FichaOrgano licitacion={l} />
          </div>
          <FichaCifras licitacion={l} columnas={2} />
          <FichaAvisos flags={l.risk_flags} />
          <FichaAcciones licitacion={l} onPreguntar={preguntar} />
        </div>

        <div className="sticky top-0 z-10 border-b border-border/60 bg-card px-4 pt-2">
          <PanelTabs
            tabs={pestanas}
            value={tab}
            onChange={setTab}
            label="Secciones de la ficha"
            idBase={idPestanas}
            className="border-b-0 pb-2"
          />
        </div>

        {/* El panel lleva foco propio (`panelDePestana`): «Resumen» puede no
            tener ningún control dentro, y el lector tiene que poder llegar. */}
        <div
          {...panelDePestana(idPestanas, tab)}
          className="px-4 pb-6 pt-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        >
          {tab === "resumen" && (
            <div className="flex flex-col gap-5">
              <section aria-labelledby={`${idPestanas}-campos`}>
                <SectionTitle as="h3" id={`${idPestanas}-campos`}>
                  Lo esencial
                </SectionTitle>
                <FichaCampos licitacion={l} variante="inspector" />
                <FichaFuente licitacion={l} className="mt-3" />
              </section>
              <FichaPuntuacion licitacion={l} />
              <FichaDescripcion licitacion={l} recortar />
              <div className="[&>*:first-child]:mt-0">
                <TecnologiasBlock licitacionId={l.id_externo} />
              </div>
              <div className="border-t border-border/50 pt-4">
                <FichaEventos licitacionId={l.id_externo} />
              </div>
            </div>
          )}

          {tab === "competencia" && (
            <div>
              {/* Contra cuántos y contra quién, antes de la baja esperada y del
                  simulador: es el contexto con el que se leen los dos. */}
              <CompetenciaEsperadaBlock licitacionId={l.id_externo} />
              <div className="mb-4.5 [&>*:first-child]:mt-0">
                <PrediccionBajaBlock licitacionId={l.id_externo} />
              </div>
              {/* F2.2 — junto a la baja esperada: es con esa baja con la que se
                  mide el rival, y el simulador la ofrece como referencia. */}
              <SimuladorPuntuacion licitacionId={l.id_externo} />
            </div>
          )}

          {tab === "pliegos" && (
            <div className="[&>*:first-child]:mt-0">
              {/* `fichaUrl` da salida cuando el enlace directo al adjunto ya no
                  responde (tokens rotativos de PLACSP) y cuando no hay ningún
                  pliego indexado. */}
              <DocumentosBlock licitacionId={l.id_externo} fichaUrl={l.url} />
              {/* Ficha estructurada (lotes, criterios, ANS, certificaciones…)
                  con citas verificables; «Extraer ficha» descarga los pliegos
                  pendientes bajo demanda. */}
              <div className="mt-6">
                <TenderFactSheetPanel licitacionId={l.id_externo} />
              </div>
              {/* F2.6 — se construye sobre los criterios de esa misma ficha. */}
              <GuionOfertaPanel licitacionId={l.id_externo} />
            </div>
          )}

          {tab === "ia" && <LicitacionAI idExterno={l.id_externo} askSignal={askSignal} />}

          {tab === "recursos" && <FichaRecursos licitacionId={l.id_externo} />}
        </div>
      </div>
    </aside>
  );
}
