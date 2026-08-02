"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { CONSOLE_SPACES } from "@/lib/console-spaces";

/**
 * Mi Pipeline — lo que está en plazo y lo que vence, en un solo reloj.
 *
 * `/pipeline-alertas` y `/renovaciones` responden a la misma pregunta en dos
 * horizontes: qué cierra pronto y qué contrato vence. Las 33 funciones
 * inventariadas de ambas rutas siguen donde estaban.
 */

const loading = () => (
  <div className="space-y-4">
    <Skeleton className="h-24 w-full rounded-xl" />
    <Skeleton className="h-[320px] w-full rounded-xl" />
  </div>
);

const VIEWS: Record<string, React.ComponentType> = {
  pipeline: dynamic(() => import("../pipeline-alertas/page"), { loading }),
  renovaciones: dynamic(() => import("../renovaciones/page"), { loading }),
};

const SPACE = CONSOLE_SPACES.find((space) => space.key === "mi-pipeline")!;

export default function MiPipelinePage() {
  const { view, setView } = useSpaceView(SPACE);
  const View = VIEWS[view] ?? VIEWS.pipeline;

  return (
    <SpaceShell spaceKey="mi-pipeline" view={view} onViewChange={setView}>
      <View />
    </SpaceShell>
  );
}
