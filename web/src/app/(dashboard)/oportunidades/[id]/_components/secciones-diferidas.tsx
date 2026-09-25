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
import { Panel, PanelLoading } from "@/components/console/panel";
import type { Pursuit } from "@/hooks/use-pursuits";

export type TabKey = "resumen" | "expediente" | "pliego" | "precio" | "conversacion";

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
const SimuladorPuntuacion = dynamic(
  () => import("@/components/pliego/simulador-puntuacion").then((modulo) => modulo.SimuladorPuntuacion),
  { loading: cargando },
);
const PursuitCommentsThread = dynamic(
  () => import("@/components/pursuits/pursuit-comments").then((modulo) => modulo.PursuitCommentsThread),
  { loading: cargando },
);

/** «Todos los campos»: el formulario entero, al final de la pestaña Resumen. */
export const EditorCompleto = dynamic(
  () => import("@/components/pursuits/pursuit-editor").then((modulo) => modulo.PursuitEditor),
  { loading: () => <PanelLoading height={420} /> },
);

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
      return (
        <>
          <PriceScenariosPanel licitacionId={pursuit.licitacion_id} />
          <Panel className="mt-4">
            <SimuladorPuntuacion licitacionId={pursuit.licitacion_id} />
          </Panel>
        </>
      );
    case "conversacion":
      return <PursuitCommentsThread pursuitId={pursuit.id} className="mx-auto h-full max-w-[760px]" />;
  }
}
