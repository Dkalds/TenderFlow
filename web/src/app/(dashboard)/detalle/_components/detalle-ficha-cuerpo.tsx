"use client";

import * as React from "react";
import { CompetenciaEsperadaBlock } from "@/components/competencia-esperada";
import { Panel, PanelTitle } from "@/components/console/panel";
import { DocumentosBlock } from "@/components/documentos-block";
import { FichaAcciones, FichaAvisos, FichaEstado, FichaOrgano } from "@/components/ficha/ficha-cabecera";
import { FichaCifras } from "@/components/ficha/ficha-cifras";
import { FichaCalendario, FichaCampos } from "@/components/ficha/ficha-campos";
import {
  FichaDescripcion,
  FichaEventos,
  FichaPuntuacion,
  FichaRecursos,
} from "@/components/ficha/ficha-secciones";
import { LicitacionAI } from "@/components/licitacion-ai";
import { GuionOfertaPanel } from "@/components/pliego/guion-oferta";
import { SimuladorPuntuacion } from "@/components/pliego/simulador-puntuacion";
import { PrediccionBajaBlock } from "@/components/prediccion-baja";
import { TenderFactSheetPanel } from "@/components/pursuits/tender-fact-sheet";
import { TecnologiasBlock } from "@/components/tecnologias-block";
import type { LicitacionDetail } from "@/lib/licitacion-detail";

/**
 * Los bloques de la ficha nacieron para apilarse en el inspector y traen su
 * propio margen superior (`mt-6`) o inferior (`mb-6`). Dentro de un `Panel`
 * ese margen es un hueco: se anula en el primero y en el último.
 */
const PANEL_DE_BLOQUES = "[&>*:first-child]:mt-0 [&>*:last-child]:mb-0";

/** El id del asistente, para llevar ahí el foco de lectura desde la cabecera. */
const ID_ASISTENTE = "ficha-completa-ia";

function irAlAsistente() {
  const destino = document.getElementById(ID_ASISTENTE);
  if (!destino) return;
  const sinMovimiento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  destino.scrollIntoView({ block: "start", behavior: sinMovimiento ? "auto" : "smooth" });
}

/**
 * El contenido de la ficha completa: todo a la vez, sin pestañas.
 *
 * Arriba lo que decide (estado, título, órgano, acciones, cifras y avisos);
 * debajo dos columnas. A la izquierda lo que publica el expediente —campos y
 * calendario, descripción, el asistente, los pliegos y su ficha—; a la
 * derecha lo que TenderFlow calcula sobre él —puntuación, competencia, baja y
 * simulador— y su historia —eventos y recursos—. Por debajo de ~1000 px las
 * dos columnas se apilan.
 */
export function DetalleFichaCuerpo({ licitacion: l }: { licitacion: LicitacionDetail }) {
  const idTitulo = React.useId();
  const idFicha = React.useId();
  const [askSignal, setAskSignal] = React.useState(0);

  const preguntar = () => {
    setAskSignal((valor) => valor + 1);
    irAlAsistente();
  };

  return (
    <article
      aria-labelledby={idTitulo}
      className="mx-auto flex w-full max-w-[1360px] flex-col gap-5 px-4 py-5 md:px-6"
    >
      <header className="flex flex-col gap-2.5">
        <FichaEstado licitacion={l} />
        <div className="flex flex-wrap items-start gap-x-8 gap-y-3">
          <div className="flex min-w-0 flex-[999_1_520px] flex-col gap-1.5">
            <h2 id={idTitulo} className="font-display text-tf-title font-semibold text-pretty">
              {l.titulo ?? l.id_externo}
            </h2>
            <FichaOrgano licitacion={l} className="text-sm" />
          </div>
          {/* En móvil el enlace al portal baja a la barra fija del pie, al
              alcance del pulgar; aquí se queda en escritorio. */}
          <FichaAcciones
            licitacion={l}
            onPreguntar={preguntar}
            conFuente
            claseFuente="max-md:hidden"
            className="flex-[1_1_320px] md:justify-end"
          />
        </div>
      </header>

      <FichaCifras licitacion={l} columnas={5} />
      <FichaAvisos flags={l.risk_flags} />

      <div className="flex flex-wrap items-start gap-5">
        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-5">
          <Panel>
            <section aria-labelledby={idFicha}>
              <PanelTitle as="h3" id={idFicha} title="Ficha" hint="Lo que publica el órgano de contratación" />
              <FichaCalendario licitacion={l} className="mb-4" />
              <FichaCampos licitacion={l} variante="completa" />
            </section>
          </Panel>
          <Panel className={PANEL_DE_BLOQUES}>
            <FichaDescripcion licitacion={l} />
            <div className="mt-5 [&>*:first-child]:mt-0">
              <TecnologiasBlock licitacionId={l.id_externo} />
            </div>
          </Panel>
          <Panel id={ID_ASISTENTE} className={`scroll-mt-4 ${PANEL_DE_BLOQUES}`}>
            <LicitacionAI idExterno={l.id_externo} askSignal={askSignal} />
          </Panel>
          {/* Sin pliegos indexados ni enlace a la ficha del portal, el bloque no
              pinta nada: `empty:hidden` no deja un panel en blanco. */}
          <Panel className={`empty:hidden ${PANEL_DE_BLOQUES}`}>
            <DocumentosBlock licitacionId={l.id_externo} fichaUrl={l.url} />
          </Panel>
          {/* La ficha estructurada y el guion traen su propia superficie. */}
          <TenderFactSheetPanel licitacionId={l.id_externo} />
          <div className="[&>*:first-child]:mt-0">
            <GuionOfertaPanel licitacionId={l.id_externo} />
          </div>
        </div>

        <div className="flex min-w-0 flex-[1_1_380px] flex-col gap-5">
          {l.score != null && (
            <Panel>
              <FichaPuntuacion licitacion={l} />
            </Panel>
          )}
          <Panel>
            <CompetenciaEsperadaBlock licitacionId={l.id_externo} className="pb-0" />
          </Panel>
          <Panel className={PANEL_DE_BLOQUES}>
            <PrediccionBajaBlock licitacionId={l.id_externo} />
            <div className="mt-5">
              <SimuladorPuntuacion licitacionId={l.id_externo} />
            </div>
          </Panel>
          <Panel>
            <FichaEventos licitacionId={l.id_externo} />
          </Panel>
          <Panel>
            <FichaRecursos licitacionId={l.id_externo} />
          </Panel>
        </div>
      </div>
    </article>
  );
}
