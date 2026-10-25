"use client";

/**
 * Lo que la ficha de la oportunidad no enseña al entrar, bajo demanda.
 *
 * La ficha abre en «Resumen». Las otras cuatro pestañas y el editor completo
 * viajaban igualmente en el First Load de la ruta, la segunda más pesada del
 * dashboard: solo el editor —zod y react-hook-form— eran ~104 KB para el
 * bloque «Todos los campos», que está al final de la pestaña. Mismo patrón que
 * las pestañas de /equipo: el contenido llega al abrir la pestaña.
 */

import dynamic from "next/dynamic";
import { toast } from "sonner";
import { Panel, PanelLoading } from "@/components/console/panel";
import { useUpdatePursuit, type Pursuit } from "@/hooks/use-pursuits";
import { formatCurrency } from "@/lib/utils";

export type TabKey = "resumen" | "expediente" | "pliego" | "precio" | "adjuntos" | "conversacion";

/** Las pestañas de la ficha, en el orden del trabajo sobre la oportunidad. */
export function pestanasDeFicha(pursuit: Pursuit): { key: TabKey; label: string; badge?: number }[] {
  return [
    { key: "resumen", label: "Resumen" },
    // El expediente vive aquí desde 2026-09: antes había que salir a
    // `/detalle` para leer órgano, CPV, plazos y pliegos de aquello sobre lo
    // que se decide en esta misma pantalla.
    { key: "expediente", label: "Expediente" },
    { key: "pliego", label: "Pliego" },
    { key: "precio", label: "Precio" },
    // C6.3 — lo que el equipo escribe para responder al pliego. Sin contador:
    // saberlo exigiría pedir la lista al abrir la ficha.
    { key: "adjuntos", label: "Adjuntos" },
    {
      key: "conversacion",
      label: "Conversación",
      badge: pursuit.comments_count ? pursuit.comments_count : undefined,
    },
  ];
}

const cargando = () => <PanelLoading height={320} />;

const ExpedientePanel = dynamic(
  () => import("@/components/pursuits/expediente-panel").then((modulo) => modulo.ExpedientePanel),
  { loading: cargando },
);
const TenderFactSheetPanel = dynamic(
  () => import("@/components/pursuits/tender-fact-sheet").then((modulo) => modulo.TenderFactSheetPanel),
  { loading: cargando },
);
const GuionOfertaPanel = dynamic(
  () => import("@/components/pliego/guion-oferta").then((modulo) => modulo.GuionOfertaPanel),
  { loading: cargando },
);
const PriceScenariosPanel = dynamic(
  () => import("@/components/pursuits/price-scenarios").then((modulo) => modulo.PriceScenariosPanel),
  { loading: cargando },
);
const MiBajaPanel = dynamic(
  () => import("@/components/pursuits/mi-baja").then((modulo) => modulo.MiBajaPanel),
  { loading: cargando },
);
const CompetenciaEsperadaBlock = dynamic(
  () => import("@/components/competencia-esperada").then((modulo) => modulo.CompetenciaEsperadaBlock),
  { loading: cargando },
);
const SimuladorPuntuacion = dynamic(
  () => import("@/components/pliego/simulador-puntuacion").then((modulo) => modulo.SimuladorPuntuacion),
  { loading: cargando },
);
const AdjuntosPanel = dynamic(
  () => import("@/components/pursuits/adjuntos-panel").then((modulo) => modulo.AdjuntosPanel),
  { loading: cargando },
);
const PursuitCommentsThread = dynamic(
  () => import("@/components/pursuits/pursuit-comments").then((modulo) => modulo.PursuitCommentsThread),
  { loading: cargando },
);

/**
 * «Editar todos los campos»: el formulario entero. Va plegado al final de la
 * pestaña Resumen y no se descarga hasta que se despliega.
 */
export const EditorCompleto = dynamic(
  () => import("@/components/pursuits/pursuit-editor").then((modulo) => modulo.PursuitEditor),
  { loading: () => <PanelLoading height={420} /> },
);

/**
 * La pestaña Precio: la competencia esperada, los escenarios —que fijan la
 * oferta prevista con un clic y pueden acotarse a esa competencia—, la baja
 * propia de la organización frente a la del mercado (C6.5) y el simulador de
 * puntuación, que ofrece como rival la baja del incumbente. El
 * lote va explícito desde el pursuit que la ficha ya tiene, en vez de que el
 * panel lo vuelva a resolver por ruta.
 */
function PestanaPrecio({ pursuit }: { pursuit: Pursuit }) {
  const actualizar = useUpdatePursuit(pursuit.id, { errorTitle: "No se pudo guardar la oferta prevista" });
  const usar = (precio: number) =>
    actualizar.mutate(
      { offer_price_eur: precio, expected_version: pursuit.version },
      {
        onSuccess: () => toast.success(`Oferta prevista: ${formatCurrency(precio)}`),
      },
    );

  return (
    <div className="flex flex-col gap-4">
      {/* Primero contra cuántos y contra quién: es con lo que se lee el precio. */}
      <Panel>
        <CompetenciaEsperadaBlock licitacionId={pursuit.licitacion_id} className="pb-0" />
      </Panel>
      <PriceScenariosPanel
        licitacionId={pursuit.licitacion_id}
        loteId={pursuit.lote_id ?? null}
        loteNumero={pursuit.lote_numero ?? null}
        ofertaPrevista={pursuit.offer_price_eur ?? null}
        onUsarPrecio={usar}
        usando={actualizar.isPending}
      />
      {/* Junto a los escenarios: lo que gana el mercado se lee contra lo que
          suele bajar la casa. */}
      <MiBajaPanel organo={pursuit.tender_organo ?? null} />
      <Panel>
        <SimuladorPuntuacion licitacionId={pursuit.licitacion_id} />
      </Panel>
    </div>
  );
}

/** El contenido de las pestañas que no son la inicial. */
export function PestanaDiferida({ tab, pursuit }: { tab: Exclude<TabKey, "resumen">; pursuit: Pursuit }) {
  switch (tab) {
    case "expediente":
      return <ExpedientePanel licitacionId={pursuit.licitacion_id} />;
    case "pliego":
      return (
        <>
          <TenderFactSheetPanel licitacionId={pursuit.licitacion_id} />
          <GuionOfertaPanel licitacionId={pursuit.licitacion_id} />
        </>
      );
    case "precio":
      return <PestanaPrecio pursuit={pursuit} />;
    case "adjuntos":
      return <AdjuntosPanel pursuitId={pursuit.id} />;
    case "conversacion":
      return <PursuitCommentsThread pursuitId={pursuit.id} className="mx-auto h-full max-w-[760px]" />;
  }
}
