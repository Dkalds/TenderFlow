"use client";

/**
 * Ajustes — un solo sitio para lo que es de uno mismo (C7.5).
 *
 * Tres de las cuatro vistas no tenían pantalla ninguna: el backend de C2 expuso
 * sesiones (C2.1), claves con tier (C2.3) y preferencias de notificación (C2.7)
 * y **nadie las consumía**. La cuarta, «datos y cuenta», vivía en `/mi-cuenta`,
 * que este espacio absorbe con la regla de siempre — consolidar no elimina: la
 * URL antigua sigue viva y redirige.
 *
 * Por eso el plan secuenció este ítem **después** de C2: un espacio de ajustes
 * creado antes habría sido una pestaña con el tema y poco más, y habría que
 * rehacerlo al llegar el contenido real.
 */

import dynamic from "next/dynamic";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { Skeleton } from "@/components/ui/skeleton";
import { CONSOLE_SPACES } from "@/lib/console-spaces";

const loading = () => <Skeleton className="h-[320px] w-full rounded-xl" />;

const VIEWS: Record<string, React.ComponentType> = {
  sesiones: dynamic(() => import("./_components/sesiones-view"), { loading }),
  claves: dynamic(() => import("./_components/claves-view"), { loading }),
  notificaciones: dynamic(() => import("./_components/notificaciones-view"), { loading }),
  cuenta: dynamic(() => import("./_components/cuenta-view"), { loading }),
};

const SPACE = CONSOLE_SPACES.find((space) => space.key === "ajustes")!;

export default function AjustesPage() {
  const { view, setView } = useSpaceView(SPACE);
  const View = VIEWS[view] ?? VIEWS.sesiones;

  return (
    <SpaceShell spaceKey="ajustes" view={view} onViewChange={setView}>
      <View />
    </SpaceShell>
  );
}
