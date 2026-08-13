"use client";

import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { CONSOLE_SPACES } from "@/lib/console-spaces";

/**
 * Mi Pipeline — tus compromisos, ordenados por lo que vence.
 *
 * Tres vistas sobre el mismo eje temporal:
 *
 * - **Agenda**: pursuits abiertos, señales sin triar y renovaciones próximas
 *   en una sola cronología por bandas de urgencia (fusión y orden en backend).
 * - **Embudo**: métricas reproducibles del funnel de pursuits.
 * - **Horizonte**: renovaciones a 3-24 meses con el CTA de anticipar.
 *
 * El inventario de funciones de las pantallas absorbidas y el destino de cada
 * una está en `docs/redesign/mi-pipeline-inventario.md`.
 */

const loading = () => (
  <div className="space-y-4">
    <Skeleton className="h-24 w-full rounded-xl" />
    <Skeleton className="h-[320px] w-full rounded-xl" />
  </div>
);

const VIEWS: Record<string, React.ComponentType> = {
  agenda: dynamic(() => import("./_components/agenda-view"), { loading }),
  embudo: dynamic(() => import("./_components/embudo-view"), { loading }),
  horizonte: dynamic(() => import("../renovaciones/page"), { loading }),
};

/**
 * `?vista=` heredados de la generación anterior del espacio. `pipeline` era la
 * pantalla de plazos del mercado (absorbida por la agenda) y `renovaciones` es
 * hoy el horizonte. Los marcadores viejos aterrizan en la vista equivalente en
 * vez de caer al default en silencio.
 */
const LEGACY_VIEWS: Record<string, string> = {
  pipeline: "agenda",
  renovaciones: "horizonte",
};

const SPACE = CONSOLE_SPACES.find((space) => space.key === "mi-pipeline")!;

export default function MiPipelinePage() {
  const params = useSearchParams();
  const { view, setView } = useSpaceView(SPACE);
  const requested = params.get("vista");
  const legacy = requested ? LEGACY_VIEWS[requested] : undefined;
  const effective = legacy ?? view;
  const View = VIEWS[effective] ?? VIEWS.agenda;

  return (
    <SpaceShell spaceKey="mi-pipeline" view={effective} onViewChange={setView}>
      <View />
    </SpaceShell>
  );
}
