"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { CONSOLE_SPACES } from "@/lib/console-spaces";

/**
 * Relaciones — los dos grafos de estructura de mercado en un espacio.
 *
 * `/red-organo-empresa` y `/ecosistema-partners` comparten pregunta (quién se
 * relaciona con quién) y ámbito; tenerlas en rutas distintas obligaba a
 * reconstruir el filtro al pasar de una a otra. Las 29 funciones inventariadas
 * de ambas siguen intactas: cada vista monta su pantalla completa.
 */

const loading = () => (
  <div className="space-y-4">
    <Skeleton className="h-24 w-full rounded-xl" />
    <Skeleton className="h-[420px] w-full rounded-xl" />
  </div>
);

const VIEWS: Record<string, React.ComponentType> = {
  "organo-empresa": dynamic(() => import("../red-organo-empresa/page"), { loading }),
  partners: dynamic(() => import("../ecosistema-partners/page"), { loading }),
};

const SPACE = CONSOLE_SPACES.find((space) => space.key === "relaciones")!;

export default function RelacionesPage() {
  const { view, setView } = useSpaceView(SPACE);
  const View = VIEWS[view] ?? VIEWS["organo-empresa"];

  return (
    <SpaceShell spaceKey="relaciones" view={view} onViewChange={setView}>
      <View />
    </SpaceShell>
  );
}
