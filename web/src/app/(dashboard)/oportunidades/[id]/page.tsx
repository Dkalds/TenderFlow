"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ExternalLink, FileDown, X } from "lucide-react";
import { PursuitLoteBadge, loteEtiqueta } from "@/components/pursuits/pursuit-presenters";
import { ChecklistGoNoGo } from "@/components/pursuits/checklist-go-no-go";
import { AdjudicacionDetectada } from "@/components/pursuits/adjudicacion-detectada";
import { KitPresentacionPanel } from "@/components/pursuits/kit-presentacion";
import { EtiquetaChips, EtiquetasEditor } from "@/components/etiquetas/etiquetas-objeto";
import { PanelError, PanelTabs, panelDePestana } from "@/components/console/panel";
import {
  ScrollEdgeDelProveedor,
  ScrollEdgeProvider,
  ScrollEdgeSentinel,
} from "@/components/layout/scroll-edge";
import { useEtiquetasDe } from "@/hooks/use-etiquetas";
import { useActiveOrganizationId, useOrganizationMembers } from "@/hooks/use-organization";
import { usePursuit } from "@/hooks/use-pursuits";
import { triggerDownload } from "@/lib/export";
import { llevarA } from "../_lib/llevar-a";
import type { LugarPaso } from "../_lib/salida-fase";
import { ANCLA_CAMPOS, CamposCompletos } from "./_components/campos-completos";
import { ColumnaDatos, type Editable } from "./_components/columna-datos";
import { DecisionComite } from "./_components/decision-comite";
import { FichaEsqueleto } from "./_components/ficha-esqueleto";
import { HistorialFicha } from "./_components/historial-ficha";
import { PathFases } from "./_components/path-fases";
import { PrecargaFicha, idDeRuta } from "./_components/precarga-ficha";
import { SalidaDeFase } from "./_components/salida-fase";
import { PestanaDiferida, type TabKey } from "./_components/secciones-diferidas";

/** Los paneles del Resumen a los que lleva un paso pendiente. */
const ANCLA_DE_LUGAR = { decision: "ficha-decision", contraste: "ficha-requisitos", kit: "ficha-kit" } as const;

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
 * datos y la próxima acción, fijos, con la cabecera fija y el scroll en la
 * pestaña. Por debajo de `xl` es una sola columna, en el orden del diseño, y la
 * cabecera scrollea con el contenido; por debajo de `md` las acciones bajan
 * bajo el título.
 *
 * Cada paso pendiente del bloque de salida lleva a donde se completa
 * (`completar`): los datos se editan en su celda y el resto de huecos tienen su
 * panel en esta misma pestaña. El formulario entero va plegado al final.
 *
 * Lo que no se ve al entrar (las otras pestañas y el editor completo) llega
 * bajo demanda (`secciones-diferidas.tsx`), y lo que solo necesita el id de la
 * URL se pide a la vez que el pursuit en vez de esperarlo (`precarga-ficha.tsx`).
 */

export default function OpportunityDetailPage() {
  const params = useParams<{ id: string }>();
  const { data: pursuit, isPending, error, refetch } = usePursuit(params.id ?? null);
  const [tab, setTab] = React.useState<TabKey>("resumen");
  const [editando, setEditando] = React.useState<Editable | null>(null);
  const [camposAbiertos, setCamposAbiertos] = React.useState(false);
  const idUrl = idDeRuta(params.id);
  // F1.6 — el id de la oportunidad es la clave del objeto etiquetable. Mientras
  // llega el pursuit vale el de la URL, que es el mismo: la petición sale ya.
  const objetoId = pursuit ? String(pursuit.id) : idUrl != null ? String(idUrl) : "";
  const etiquetas = useEtiquetasDe("oportunidad", objetoId ? [objetoId] : []);
  // El historial guarda ids de actor; los nombres son los de la organización,
  // la misma lista que ya pide el editor de responsable. Mientras llega el
  // pursuit se piden los de la organización activa, que es con la que se
  // pregunta por él: si fuese de otra, el backend responde 403.
  const organizacionActiva = useActiveOrganizationId();
  const miembros = useOrganizationMembers(pursuit?.organization_id ?? organizacionActiva);
  // Va como primer hijo del `div` raíz en las tres salidas de abajo, y eso es
  // lo que hace que React no lo desmonte al llegar el pursuit: sus consultas
  // pasan a los componentes de «Resumen» sin quedarse un instante sin
  // observador (React Query cancela la petición en vuelo de una consulta que se
  // queda sin ninguno si su `queryFn` usa el `signal`).
  const precarga = idUrl != null && (isPending || tab === "resumen") ? <PrecargaFicha pursuitId={idUrl} /> : null;

  if (isPending) {
    // El mismo esqueleto que el `loading.tsx` de la ruta: la página enseña lo
    // mismo mientras pide la oportunidad (ver `ficha-esqueleto.tsx`).
    return (
      <div className="contents">
        {precarga}
        <FichaEsqueleto />
      </div>
    );
  }

  if (error || !pursuit) {
    return (
      <div className="grid h-[calc(100vh-var(--alto-cromo))] place-items-center p-10">
        {precarga}
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

  const completar = (lugar: LugarPaso) => {
    if (lugar === "oferta" || lugar === "responsable" || lugar === "proxima") {
      // El editor se abre en su celda y se lleva el foco; enfocarlo lo trae a
      // la vista si la columna de datos estaba fuera.
      setEditando(lugar);
    } else if (lugar === "campos") {
      setCamposAbiertos(true);
      // Al siguiente fotograma, con el cuerpo ya montado.
      requestAnimationFrame(() => llevarA(ANCLA_CAMPOS));
    } else {
      llevarA(ANCLA_DE_LUGAR[lugar]);
    }
  };
  const columnaDatos = <ColumnaDatos pursuit={pursuit} editando={editando} onEditar={setEditando} />;

  return (
    // Por debajo de `xl` la cabecera scrollea con el contenido: con título,
    // path y pestañas mide más que la pantalla de un móvil, y fija dejaba a la
    // pestaña una caja de scroll de ~48px. Es un bloque y no un flex para que
    // el centinela no encoja a 0px. `relative` para que los `<select>` nativos
    // ocultos de Radix y los `sr-only` del editor, que son absolutos, scrolleen
    // con la caja en vez de estirar el documento. En `xl` vuelve a ser la
    // columna de siempre: cabecera fija y scroll en la pestaña.
    <div className="relative h-[calc(100vh-var(--alto-cromo))] min-h-0 overflow-y-auto xl:static xl:flex xl:flex-col xl:overflow-visible">
      {precarga}
      {/* Borde de scroll propio, como `SpaceShell`: por debajo de `xl` scrollea
          esta caja y no `#main-content`, así que el centinela del marco no se
          entera. El borde va `sticky` dentro de la caja para que ella siga
          siendo la raíz del `precarga` de arriba; en `xl` no scrollea y el
          borde no aparece nunca. `PrecargaFicha` no pinta nada, así que el
          centinela sigue siendo el primer elemento de la caja. */}
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
            idBase="ficha"
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

      {/* Solo en `xl` es esta la caja con scroll, y solo ahí la columna de
          datos es `sticky`: por debajo scrollea la raíz, cabecera incluida.
          Por eso el `relative` que la raíz deja en `xl:static` pasa aquí en
          `xl`: sin él, los `<select>` ocultos del editor colgaban del viewport
          y el documento medía 1356 px a 1366×768. En la raíz solo movería el
          desborde a `#main-content`. */}
      <div className="px-4 pt-4 pb-8 xl:relative xl:min-h-0 xl:flex-1 xl:overflow-y-auto">
        <div {...panelDePestana("ficha", tab)} className="rounded-lg">
          {tab === "resumen" ? (
            <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
              <div className="flex min-w-0 flex-col gap-3.5">
                {/* Cierre asistido: sólo aparece cuando la ingesta ya conoce una
                    adjudicación de este expediente. */}
                <AdjudicacionDetectada pursuit={pursuit} />
                <SalidaDeFase pursuit={pursuit} onCompletar={completar} />
                <DecisionComite key={version} pursuit={pursuit} />
              </div>

              {columnaDatos}

              {/* Lo que sostiene la decisión y el trabajo de la oferta, lo que
                  ha pasado y, plegado, el formulario entero. */}
              <div className="flex min-w-0 flex-col gap-3.5 xl:col-start-1">
                <ChecklistGoNoGo
                  pursuitId={pursuit.id}
                  licitacionId={pursuit.licitacion_id}
                  onAbrirPliego={() => {
                    setTab("pliego");
                    // El enlace desaparece con la pestaña: el foco va a la
                    // pestaña de destino en vez de caer al `body`.
                    requestAnimationFrame(() => document.getElementById("ficha-tab-pliego")?.focus());
                  }}
                />
                <KitPresentacionPanel pursuitId={pursuit.id} organizationId={pursuit.organization_id} />
                <HistorialFicha pursuit={pursuit} miembros={miembros.data ?? []} />
                <CamposCompletos pursuit={pursuit} abierto={camposAbiertos} onAlternar={setCamposAbiertos} />
              </div>
            </div>
          ) : tab === "pliego" || tab === "precio" ? (
            <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
              <div className="min-w-0">
                <PestanaDiferida tab={tab} pursuit={pursuit} />
              </div>
              {columnaDatos}
            </div>
          ) : (
            <PestanaDiferida tab={tab} pursuit={pursuit} />
          )}
        </div>
      </div>
    </div>
  );
}
