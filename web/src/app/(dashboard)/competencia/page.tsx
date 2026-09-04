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
 *
 * Los cuerpos viven en `_components/`, no en los `page.tsx` de las rutas
 * absorbidas. Este espacio los importaba de allí (`../competidores/page`,
 * `../utes/page`) y eso convertía a cada uno en boundary de ruta y componente a
 * la vez — un `page.tsx` montado a mano no recibe el contrato
 * `params`/`searchParams` de Next, y además aquellas rutas no se alcanzaban:
 * los 308 de `next.config.ts` se resuelven antes que el enrutado por ficheros.
 * Quien preserva los enlaces guardados es el redirect, no el fichero.
 */

const loading = () => (
  <div className="space-y-4">
    <Skeleton className="h-24 w-full rounded-xl" />
    <Skeleton className="h-[320px] w-full rounded-xl" />
  </div>
);

const VIEWS: Record<string, React.ComponentType> = {
  competidores: dynamic(() => import("./_components/competidores-view"), { loading }),
  utes: dynamic(() => import("./_components/utes-view"), { loading }),
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
