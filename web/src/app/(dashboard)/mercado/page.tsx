"use client";

import dynamic from "next/dynamic";
import { ExportPopover } from "@/components/export-popover";
import { Skeleton } from "@/components/ui/skeleton";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { CONSOLE_SPACES } from "@/lib/console-spaces";
import { useFeatureFlag } from "@/hooks/use-feature-flag";

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
 *
 * Las vistas viven en `_components/<x>-view.tsx` y las consumen dos entradas:
 * este espacio y el `page.tsx` de la ruta heredada. Hasta 2026-08 este módulo
 * importaba directamente esos `page.tsx`, así que cada uno era a la vez
 * boundary de ruta y componente y Next no podía tratarlo como lo primero.
 */

const loading = () => (
  <div className="space-y-4">
    <Skeleton className="h-24 w-full rounded-xl" />
    <Skeleton className="h-[320px] w-full rounded-xl" />
  </div>
);

const VIEWS: Record<string, React.ComponentType> = {
  tiempo: dynamic(() => import("./_components/tendencias-view"), { loading }),
  cpv: dynamic(() => import("./_components/tendencias-cpv-view"), { loading }),
  calendario: dynamic(() => import("./_components/calendario-view"), { loading }),
  geografia: dynamic(() => import("./_components/geografia-view"), { loading }),
  tecnologias: dynamic(() => import("./_components/tecnologias-view"), { loading }),
  organos: dynamic(() => import("./_components/organos-view"), { loading }),
  clusters: dynamic(() => import("./_components/clusters-view"), { loading }),
  proyectos: dynamic(() => import("./_components/proyectos-modulos-view"), { loading }),
};

const SPACE = CONSOLE_SPACES.find((space) => space.key === "mercado")!;

/**
 * Las dos vistas `experimental` y la fila de `feature_flags` que las gobierna.
 * Son los mismos nombres que pasan `clusters-view.tsx` y
 * `proyectos-modulos-view.tsx` a `VistaExperimental`.
 */
const FLAG_CLUSTERS = "mercado_clusters";
const FLAG_PROYECTOS = "mercado_proyectos_modulos";

/**
 * Marca en el conmutador las vistas que `/ops` apagó.
 *
 * `VistaExperimental` ya se niega a montar una vista con su flag en `false`,
 * pero la pestaña seguía anunciándola como una más: el usuario pulsaba para
 * descubrir que estaba apagada. Aquí se dice antes de pulsar. Sólo cuenta un
 * **no** explícito del backend: sin respuesta, el fail-open de `useFeatureFlag`
 * deja la pestaña como estaba.
 */
function useBadgesDeFlags(): Record<string, string> | undefined {
  const clusters = useFeatureFlag(FLAG_CLUSTERS);
  const proyectos = useFeatureFlag(FLAG_PROYECTOS);
  const badges: Record<string, string> = {};
  if (!clusters.enabled) badges.clusters = "apagada";
  if (!proyectos.enabled) badges.proyectos = "apagada";
  return Object.keys(badges).length > 0 ? badges : undefined;
}

export default function MercadoPage() {
  const { view, setView } = useSpaceView(SPACE);
  const View = VIEWS[view] ?? VIEWS.tiempo;
  const viewBadges = useBadgesDeFlags();

  return (
    <SpaceShell
      spaceKey="mercado"
      view={view}
      onViewChange={setView}
      viewBadges={viewBadges}
      actions={
        <ExportPopover className="[&>button]:h-7 [&>button]:px-2.5 [&>button]:py-0 [&>button]:text-xs" />
      }
    >
      <View />
    </SpaceShell>
  );
}
