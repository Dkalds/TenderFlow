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
 *
 * Las tres viven en `_components/`. El horizonte se importaba de
 * `../renovaciones/page`, lo que hacía de aquel fichero boundary de ruta y
 * componente a la vez: como componente no recibía el contrato
 * `params`/`searchParams`, y como ruta no se ejecutaba nunca —`/renovaciones`
 * la redirige `next.config.ts` con un 308, y los redirects de Next corren antes
 * que el enrutado por sistema de ficheros—.
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
  horizonte: dynamic(() => import("./_components/horizonte-view"), { loading }),
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
