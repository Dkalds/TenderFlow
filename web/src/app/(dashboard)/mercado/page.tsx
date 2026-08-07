"use client";

import dynamic from "next/dynamic";
import { ExportPopover } from "@/components/export-popover";
import { Skeleton } from "@/components/ui/skeleton";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { CONSOLE_SPACES } from "@/lib/console-spaces";

/**
 * Mercado — las ocho rutas analíticas como cortes de una sola superficie.
 *
 * `/tendencias`, `/tendencias-cpv`, `/calendario`, `/geografia`,
 * `/tecnologias`, `/organos`, `/clusters` y `/proyectos-modulos` eran el mismo
 * dataset mirado de ocho maneras, cada una en su página y con su propio menú.
 * Aquí son vistas de un espacio: **el ámbito sobrevive al cambio de corte**,
 * porque cambiar de vista no navega, sólo cambia qué se pinta.
 *
 * Cada vista monta la pantalla original tal cual, así que las 88 funciones
 * inventariadas de esas ocho rutas siguen exactamente donde estaban. Se cargan
 * bajo demanda (`next/dynamic`): ocho pantallas de gráficos en un solo bundle
 * costarían el arranque del espacio entero para ver un corte.
 */

const loading = () => (
  <div className="space-y-4">
    <Skeleton className="h-24 w-full rounded-xl" />
    <Skeleton className="h-[320px] w-full rounded-xl" />
  </div>
);

const VIEWS: Record<string, React.ComponentType> = {
  tiempo: dynamic(() => import("../tendencias/page"), { loading }),
  cpv: dynamic(() => import("../tendencias-cpv/page"), { loading }),
  calendario: dynamic(() => import("../calendario/page"), { loading }),
  geografia: dynamic(() => import("../geografia/page"), { loading }),
  tecnologias: dynamic(() => import("../tecnologias/page"), { loading }),
  organos: dynamic(() => import("../organos/page"), { loading }),
  clusters: dynamic(() => import("../clusters/page"), { loading }),
  proyectos: dynamic(() => import("../proyectos-modulos/page"), { loading }),
  red: dynamic(() => import("../red-organo-empresa/page"), { loading }),
};

const SPACE = CONSOLE_SPACES.find((space) => space.key === "mercado")!;

export default function MercadoPage() {
  const { view, setView } = useSpaceView(SPACE);
  const View = VIEWS[view] ?? VIEWS.tiempo;

  return (
    <SpaceShell
      spaceKey="mercado"
      view={view}
      onViewChange={setView}
      actions={
        <ExportPopover className="[&>button]:h-7 [&>button]:px-2.5 [&>button]:py-0 [&>button]:text-xs" />
      }
    >
      <View />
    </SpaceShell>
  );
}
