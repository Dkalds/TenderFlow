"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ExternalLink, FileDown, X } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { PursuitCommentsThread } from "@/components/pursuits/pursuit-comments";
import { PursuitEditor } from "@/components/pursuits/pursuit-editor";
import { PriceScenariosPanel } from "@/components/pursuits/price-scenarios";
import { PursuitLoteBadge, loteEtiqueta } from "@/components/pursuits/pursuit-presenters";
import { TenderFactSheetPanel } from "@/components/pursuits/tender-fact-sheet";
import { GuionOfertaPanel } from "@/components/pliego/guion-oferta";
import { SimuladorPuntuacion } from "@/components/pliego/simulador-puntuacion";
import { ChecklistGoNoGo } from "@/components/pursuits/checklist-go-no-go";
import { AdjudicacionDetectada } from "@/components/pursuits/adjudicacion-detectada";
import { ExpedientePanel } from "@/components/pursuits/expediente-panel";
import { PursuitActivity } from "@/components/pursuits/pursuit-activity";
import { KitPresentacionPanel } from "@/components/pursuits/kit-presentacion";
import { EtiquetaChips, EtiquetasEditor } from "@/components/etiquetas/etiquetas-objeto";
import { Panel, PanelError, PanelTabs, SectionTitle } from "@/components/console/panel";
import {
  ScrollEdgeDelProveedor,
  ScrollEdgeProvider,
  ScrollEdgeSentinel,
} from "@/components/layout/scroll-edge";
import { useEtiquetasDe } from "@/hooks/use-etiquetas";
import { useOrganizationMembers } from "@/hooks/use-organization";
import { usePursuit } from "@/hooks/use-pursuits";
import { triggerDownload } from "@/lib/export";
import { DecisionComite } from "./_components/decision-comite";
import { FichaDatos } from "./_components/ficha-datos";
import { PathFases } from "./_components/path-fases";
import { ProximaAccion } from "./_components/proxima-accion";
import { SalidaDeFase } from "./_components/salida-fase";

/**
 * Ficha de la oportunidad — el path de fases primero.
 *
 * La cabecera dice **en qué punto del workflow está** y el primer bloque, qué
 * falta para salir de esa fase y cuál es el único paso posible. Antes la ficha
 * abría con el formulario completo: para avanzar había que saber que el estado
 * es un desplegable, y nada decía qué se esperaba de la fase actual.
 *
 * No se ha quitado nada. El editor completo, el contraste del pliego, el kit,
 * los escenarios de precio y la conversación siguen siendo los mismos
 * componentes; lo que cambia es el orden y qué se toca primero. Los tres
 * controles del día a día —avanzar, decidir y apuntar la próxima acción— son
 * ahora un clic desde arriba, y cada uno manda su propio PATCH con
 * `expected_version`.
 *
 * Las tres columnas del diseño no caben en una pantalla de consola, así que en
 * `xl` la ficha se parte: a la izquierda lo que se trabaja, a la derecha los
 * datos y el historial, con la cabecera fija y el scroll en la pestaña. Por
 * debajo de `xl` es una sola columna, en el orden del diseño, y la cabecera
 * scrollea con el contenido; por debajo de `md` las acciones bajan bajo el
 * título.
 */

type TabKey = "resumen" | "expediente" | "pliego" | "precio" | "conversacion";

export default function OpportunityDetailPage() {
  const params = useParams<{ id: string }>();
  const { data: pursuit, isPending, error, refetch } = usePursuit(params.id ?? null);
  const [tab, setTab] = React.useState<TabKey>("resumen");
  // F1.6 — el id de la oportunidad es la clave del objeto etiquetable.
  const objetoId = pursuit ? String(pursuit.id) : "";
  const etiquetas = useEtiquetasDe("oportunidad", objetoId ? [objetoId] : []);
  // El historial guarda ids de actor; los nombres son los de la organización,
  // la misma lista que ya pide el editor de responsable.
  const miembros = useOrganizationMembers(pursuit?.organization_id ?? null);

  if (isPending) {
    return (
      <div className="flex h-[calc(100vh-var(--alto-cromo))] min-h-0 flex-col gap-3 p-4">
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-[360px] w-full rounded-xl" />
      </div>
    );
  }

  if (error || !pursuit) {
    return (
      <div className="grid h-[calc(100vh-var(--alto-cromo))] place-items-center p-10">
        <PanelError
          title="No se pudo abrir esta oportunidad"
          detail={error instanceof Error ? error.message : "No encontrada"}
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  const alcance = loteEtiqueta(pursuit);
  const version = `${pursuit.id}:${pursuit.version}`;

  return (
    // Por debajo de `xl` la cabecera scrollea con el contenido: con título,
    // path y pestañas mide más que la pantalla de un móvil, y fija dejaba a la
    // pestaña una caja de scroll de ~48px. Es un bloque y no un flex para que
    // el centinela no encoja a 0px. `relative` para que los `<select>` nativos
    // ocultos de Radix y los `sr-only` del editor, que son absolutos, scrolleen
    // con la caja en vez de estirar el documento. En `xl` vuelve a ser la
    // columna de siempre: cabecera fija y scroll en la pestaña.
    <div className="relative h-[calc(100vh-var(--alto-cromo))] min-h-0 overflow-y-auto xl:static xl:flex xl:flex-col xl:overflow-visible">
      {/* Borde de scroll propio, como `SpaceShell`: por debajo de `xl` scrollea
          esta caja y no `#main-content`, así que el centinela del marco no se
          entera. El borde va `sticky` dentro de la caja para que ella siga
          siendo la raíz; en `xl` no scrollea y el borde no aparece nunca. */}
      <ScrollEdgeProvider>
        <ScrollEdgeSentinel />
        <div className="pointer-events-none sticky top-0 z-30 h-0">
          <ScrollEdgeDelProveedor />
        </div>
      </ScrollEdgeProvider>
      <header className="border-border/60 bg-card/40 flex-none border-b px-4 pt-3.5">
        {/* Bajo `md` las acciones van debajo del título: en la misma fila sus
            ~290px dejaban el título a una palabra por línea. */}
        <div className="flex flex-col gap-2.5 md:flex-row md:items-start md:gap-3">
          <div className="min-w-0 flex-1">
            <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
              <span className="text-muted-foreground font-mono text-tf-micro font-semibold tracking-wider uppercase">
                {pursuit.licitacion_id}
              </span>
              {/* El lote va aquí y no en el título: dos oportunidades del mismo
                  expediente comparten título y sólo el lote las separa. */}
              {alcance ? (
                <PursuitLoteBadge pursuit={pursuit} />
              ) : (
                <span className="text-muted-foreground text-tf-micro">Expediente completo</span>
              )}
              <EtiquetaChips etiquetas={etiquetas.data?.[objetoId]} />
              <EtiquetasEditor
                objetoTipo="oportunidad"
                objetoId={objetoId}
                aplicadas={etiquetas.data?.[objetoId]}
                descripcion="esta oportunidad"
              />
            </div>

            <h1 className="font-display max-w-[74ch] text-tf-title leading-[1.2] font-semibold tracking-[-0.015em] text-pretty">
              {pursuit.tender_title ?? `Licitación ${pursuit.licitacion_id}`}
            </h1>

            <p className="text-muted-foreground mt-1 text-tf-body">
              {pursuit.tender_organo ?? `Referencia ${pursuit.licitacion_id}`} ·{" "}
              {pursuit.responsible_name ?? "Sin responsable"}
            </p>
          </div>

          <div className="flex flex-none items-center gap-3">
            {/* F2.7 — el one-pager para dirección. El backend lo servía desde
                `GET /pursuits/{id}/ficha.pdf` y ninguna pantalla lo pedía. */}
            <button
              type="button"
              onClick={() => void triggerDownload(`/api/v1/pursuits/${pursuit.id}/ficha.pdf`)}
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-tf-meta font-medium"
            >
              <FileDown className="h-3 w-3" aria-hidden="true" />
              Descargar PDF
            </button>
            <Link
              href={`/detalle?lic=${encodeURIComponent(pursuit.licitacion_id)}`}
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-tf-meta font-medium"
            >
              Ver anuncio original <ExternalLink className="h-3 w-3" aria-hidden="true" />
            </Link>
            {/* `ml-auto`: bajo el título, el cierre queda en el extremo derecho
                de la fila. Al lado del título el grupo mide lo que su contenido
                y el margen no mueve nada. */}
            <Link
              href="/oportunidades"
              aria-label="Cerrar la ficha"
              className="border-border/60 text-muted-foreground hover:text-foreground ml-auto grid h-8 w-8 flex-none place-items-center rounded-lg border transition-colors"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </Link>
          </div>
        </div>

        <PathFases pursuit={pursuit} className="mt-3.5" />

        <div className="mt-3">
          <PanelTabs
            label="Secciones de la oportunidad"
            value={tab}
            onChange={setTab}
            tabs={[
              { key: "resumen", label: "Resumen" },
              // El expediente vive aquí desde 2026-09: antes había que salir a
              // `/detalle` para leer órgano, CPV, plazos y pliegos de aquello
              // sobre lo que se decide en esta misma pantalla.
              { key: "expediente", label: "Expediente" },
              { key: "pliego", label: "Pliego" },
              { key: "precio", label: "Precio" },
              {
                key: "conversacion",
                label: "Conversación",
                badge: pursuit.comments_count ? pursuit.comments_count : undefined,
              },
            ]}
          />
        </div>
      </header>

      <div className="px-4 pt-4 pb-8 xl:min-h-0 xl:flex-1 xl:overflow-y-auto">
        {tab === "resumen" && (
          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
            <div className="flex flex-col gap-3.5">
              {/* Cierre asistido: sólo aparece cuando la ingesta ya conoce una
                  adjudicación de este expediente. */}
              <AdjudicacionDetectada pursuit={pursuit} />
              <SalidaDeFase pursuit={pursuit} />
              <DecisionComite key={version} pursuit={pursuit} />
            </div>

            <aside className="flex flex-col gap-3.5 xl:col-start-2 xl:row-span-2 xl:row-start-1">
              <FichaDatos pursuit={pursuit} />
              <ProximaAccion key={version} pursuit={pursuit} />
              <Panel>
                {/* El ledger `pursuit_events` se persistía desde v61 y no lo
                    pintaba ninguna pantalla: en un espacio compartido nadie
                    veía quién había movido qué. */}
                <SectionTitle>Historial</SectionTitle>
                <PursuitActivity events={pursuit.events} miembros={miembros.data ?? []} />
              </Panel>
              <p className="text-muted-foreground px-1 text-tf-micro leading-relaxed">
                Los escenarios se basan en el universo observado. La decisión y el precio final
                siguen siendo responsabilidad del equipo.
              </p>
            </aside>

            {/* Lo que sostiene la decisión y el trabajo de la oferta. Cada panel
                trae su propio margen superior, así que aquí no hay `gap`. */}
            <div className="xl:col-start-1">
              <ChecklistGoNoGo pursuitId={pursuit.id} licitacionId={pursuit.licitacion_id} />
              <KitPresentacionPanel
                pursuitId={pursuit.id}
                organizationId={pursuit.organization_id}
              />
              <div className="mt-4">
                <SectionTitle>Todos los campos</SectionTitle>
                <PursuitEditor pursuit={pursuit} />
              </div>
            </div>
          </div>
        )}

        {tab === "expediente" && <ExpedientePanel licitacionId={pursuit.licitacion_id} />}

        {tab === "pliego" && (
          <>
            <TenderFactSheetPanel licitacionId={pursuit.licitacion_id} />
            <GuionOfertaPanel licitacionId={pursuit.licitacion_id} />
          </>
        )}
        {tab === "precio" && (
          <>
            <PriceScenariosPanel licitacionId={pursuit.licitacion_id} />
            <Panel className="mt-4">
              <SimuladorPuntuacion licitacionId={pursuit.licitacion_id} />
            </Panel>
          </>
        )}
        {tab === "conversacion" && (
          <PursuitCommentsThread pursuitId={pursuit.id} className="mx-auto h-full max-w-[760px]" />
        )}
      </div>
    </div>
  );
}
