"use client";

import * as React from "react";
import { CompetenciaEsperadaBlock } from "@/components/competencia-esperada";
import { Panel, PanelTitle } from "@/components/console/panel";
import { DocumentosBlock } from "@/components/documentos-block";
import { FichaAcciones, FichaAvisos, FichaEstado, FichaOrgano } from "@/components/ficha/ficha-cabecera";
import { FichaCifras } from "@/components/ficha/ficha-cifras";
import { FichaAdjudicatarios } from "@/components/ficha/ficha-adjudicatarios";
import { FichaRequisitos } from "@/components/ficha/ficha-requisitos";
import { FichaSimilares } from "@/components/ficha/ficha-similares";
import { FichaCalendario, FichaCampos } from "@/components/ficha/ficha-campos";
import {
  FichaDescripcion,
  FichaEventos,
  FichaFuente,
  FichaPuntuacion,
  FichaRecursos,
} from "@/components/ficha/ficha-secciones";
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

/**
 * Las secciones, en el orden en que se decide: qué es, qué piden, qué dicen
 * los pliegos, contra quién y qué le ha pasado. El índice de arriba salta a
 * cada una; la ficha completa es larga y sin él había que desplazarse a ciegas.
 */
const SECCIONES = [
  { id: "ficha-expediente", label: "Expediente" },
  { id: "ficha-requisitos", label: "Requisitos" },
  { id: "ficha-pliegos", label: "Pliegos" },
  { id: "ficha-competencia", label: "Competencia" },
  { id: "ficha-historia", label: "Historia" },
] as const;

/** `scroll-mt` deja el título de la sección a la vista bajo el índice pegajoso. */
const SECCION = "flex scroll-mt-16 flex-col gap-5";

function IndiceDeSecciones() {
  return (
    <nav
      aria-label="Secciones de la ficha"
      className="tf-glass-strong sticky top-0 z-10 -mx-1 flex gap-1 overflow-x-auto rounded-lg border border-divider p-1 [scrollbar-width:none]"
    >
      {SECCIONES.map((seccion) => (
        <a
          key={seccion.id}
          href={`#${seccion.id}`}
          className="flex-none rounded-md px-2.5 py-1 text-tf-meta font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
        >
          {seccion.label}
        </a>
      ))}
    </nav>
  );
}

/**
 * El contenido de la ficha completa: todo a la vez, sin pestañas.
 *
 * Arriba lo que decide (estado, título, órgano, acciones, cifras y avisos) y
 * el índice de secciones. Debajo dos columnas: a la izquierda lo que publica
 * el expediente —el expediente en sí, sus requisitos (lotes, criterios,
 * garantías y solvencia del anuncio) y los pliegos con su ficha y el guion—;
 * a la derecha lo que TenderFlow calcula sobre él —puntuación, competencia,
 * baja, simulador y parecidos— y su historia, eventos y recursos. Por debajo
 * de ~1000 px las dos columnas se apilan.
 *
 * El asistente no tiene panel aquí desde 2026-10: «Preguntar a la IA» de la
 * cabecera abre el asistente único con este expediente, con su resumen.
 */
export function DetalleFichaCuerpo({ licitacion: l }: { licitacion: LicitacionDetail }) {
  const idTitulo = React.useId();
  const idFicha = React.useId();

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
            conFuente
            claseFuente="max-md:hidden"
            className="flex-[1_1_320px] md:justify-end"
          />
        </div>
      </header>

      <FichaCifras licitacion={l} columnas={5} />
      <FichaAvisos flags={l.risk_flags} />
      <IndiceDeSecciones />

      <div className="flex flex-wrap items-start gap-5">
        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-5">
          <section id="ficha-expediente" aria-labelledby={idFicha} className={SECCION}>
            <Panel>
              <PanelTitle as="h3" id={idFicha} title="Expediente" hint="Lo que publica el órgano de contratación" />
              <FichaCalendario licitacion={l} className="mb-4" />
              <FichaCampos licitacion={l} variante="completa" />
              <FichaFuente licitacion={l} className="mt-3" />
            </Panel>
            {/* Sin adjudicatario y sin estar adjudicado no pinta nada:
                `empty:hidden` no deja un panel en blanco. */}
            <Panel className="empty:hidden">
              <FichaAdjudicatarios licitacion={l} />
            </Panel>
            <Panel className={PANEL_DE_BLOQUES}>
              <FichaDescripcion licitacion={l} />
              <div className="mt-5 [&>*:first-child]:mt-0">
                <TecnologiasBlock licitacionId={l.id_externo} />
              </div>
            </Panel>
          </section>

          <section id="ficha-requisitos" aria-label="Requisitos" className={SECCION}>
            <Panel>
              <PanelTitle as="h3" title="Requisitos" hint="Lotes, criterios, garantías y solvencia del anuncio" />
              <FichaRequisitos licitacion={l} as="h4" />
            </Panel>
          </section>

          <section id="ficha-pliegos" aria-label="Pliegos" className={SECCION}>
            {/* Sin pliegos indexados ni enlace a la ficha del portal, el bloque
                no pinta nada: `empty:hidden` no deja un panel en blanco. */}
            <Panel className={`empty:hidden ${PANEL_DE_BLOQUES}`}>
              <DocumentosBlock licitacionId={l.id_externo} fichaUrl={l.url} />
            </Panel>
            {/* La ficha estructurada y el guion traen su propia superficie. La
                publicación oficial ya está en Requisitos: aquí, solo lo
                extraído del pliego. */}
            <TenderFactSheetPanel licitacionId={l.id_externo} conCondiciones={false} />
            <div className="[&>*:first-child]:mt-0">
              <GuionOfertaPanel licitacionId={l.id_externo} />
            </div>
          </section>
        </div>

        <div className="flex min-w-0 flex-[1_1_380px] flex-col gap-5">
          <section id="ficha-competencia" aria-label="Competencia" className={SECCION}>
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
              <FichaSimilares licitacionId={l.id_externo} />
            </Panel>
          </section>

          <section id="ficha-historia" aria-label="Historia" className={SECCION}>
            <Panel>
              <FichaEventos licitacionId={l.id_externo} />
            </Panel>
            <Panel>
              <FichaRecursos licitacionId={l.id_externo} />
            </Panel>
          </section>
        </div>
      </div>
    </article>
  );
}
