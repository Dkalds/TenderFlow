"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { CONSOLE_SPACES } from "@/lib/console-spaces";

/**
 * Competencia — `/competidores` y `/utes` como dos cortes del mismo análisis.
 *
 * Las dos rutas responden a la misma pregunta (quién gana y con quién) sobre el
 * mismo ámbito, y separarlas obligaba a re-aplicar el filtro al cruzar. Cada
 * vista monta su pantalla original completa: las 34 funciones inventariadas
 * siguen donde estaban, incluido el dossier de empresa y su análisis completo.
 */

const loading = () => (
  <div className="space-y-4">
    <Skeleton className="h-24 w-full rounded-xl" />
    <Skeleton className="h-[320px] w-full rounded-xl" />
  </div>
);

const VIEWS: Record<string, React.ComponentType> = {
  competidores: dynamic(() => import("../competidores/page"), { loading }),
  utes: dynamic(() => import("../utes/page"), { loading }),
};

const SPACE = CONSOLE_SPACES.find((space) => space.key === "competencia")!;

export default function CompetenciaPage() {
  const { view, setView } = useSpaceView(SPACE);
  const View = VIEWS[view] ?? VIEWS.competidores;

  return (
    <SpaceShell spaceKey="competencia" view={view} onViewChange={setView}>
      <View />
    </SpaceShell>
  );
}
