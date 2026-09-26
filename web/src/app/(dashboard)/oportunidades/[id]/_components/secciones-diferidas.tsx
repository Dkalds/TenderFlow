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
import { ApiError } from "@/lib/api-client";
import { formatCurrency } from "@/lib/utils";

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

/**
 * «Editar todos los campos»: el formulario entero. Va plegado al final de la
 * pestaña Resumen y no se descarga hasta que se despliega.
 */
export const EditorCompleto = dynamic(
  () => import("@/components/pursuits/pursuit-editor").then((modulo) => modulo.PursuitEditor),
  { loading: () => <PanelLoading height={420} /> },
);

/**
 * La pestaña Precio: los escenarios, que ahora fijan la oferta prevista con un
 * clic, y el simulador de puntuación. El lote va explícito desde el pursuit
 * que la ficha ya tiene, en vez de que el panel lo vuelva a resolver por ruta.
 */
function PestanaPrecio({ pursuit }: { pursuit: Pursuit }) {
  const actualizar = useUpdatePursuit(pursuit.id);
  const usar = (precio: number) =>
    actualizar.mutate(
      { offer_price_eur: precio, expected_version: pursuit.version },
      {
        onSuccess: () => toast.success(`Oferta prevista: ${formatCurrency(precio)}`),
        onError: (error) =>
          toast.error(
            error instanceof ApiError && error.status === 409
              ? "Alguien del equipo la cambió mientras la tenías abierta"
              : "No se pudo guardar la oferta prevista",
            { description: error instanceof Error ? error.message : undefined },
          ),
      },
    );

  return (
    <div className="flex flex-col gap-4">
      <PriceScenariosPanel
        licitacionId={pursuit.licitacion_id}
        loteId={pursuit.lote_id ?? null}
        loteNumero={pursuit.lote_numero ?? null}
        ofertaPrevista={pursuit.offer_price_eur ?? null}
        onUsarPrecio={usar}
        usando={actualizar.isPending}
      />
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
    case "conversacion":
      return <PursuitCommentsThread pursuitId={pursuit.id} className="mx-auto h-full max-w-[760px]" />;
  }
}
