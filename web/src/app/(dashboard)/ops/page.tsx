"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { useSession } from "@/lib/auth";
import { CONSOLE_SPACES } from "@/lib/console-spaces";
import { VISTAS_FUSIONADAS } from "@/lib/space-views";
import { formatNumber } from "@/lib/utils";
import { OpsHealthStrip } from "./_components/health-strip";
import { useEjecuciones } from "./_hooks/use-ejecuciones";
import { usePendientesDeAcceso } from "./_hooks/use-solicitudes-acceso";

/**
 * Ops y Admin — el turno de guardia bajo una sola puerta.
 *
 * Cinco vistas: saber si el sistema responde (Estado), si lo que corre solo
 * corrió (Ejecuciones), si el dato llega bien (Datos), y dos de trabajo y
 * gobierno (Etiquetado, Administración). Nació absorbiendo seis rutas; la
 * reagrupación de 2026-10 fundió dos de ellas —Feature flags y Webhooks— en
 * Administración y añadió Ejecuciones. Sus `?vista=` y sus rutas heredadas
 * siguen entrando (`VISTAS_FUSIONADAS` en `lib/space-views.ts`).
 *
 * Las vistas viven en `_components/<x>-view.tsx`, cada una con su propia guarda
 * de administrador donde la necesita. Hasta 2026-08 este módulo importaba
 * directamente los `page.tsx` de las rutas, así que cada uno era a la vez
 * boundary de ruta y componente y Next no podía tratarlo como lo primero.
 */

const loading = () => (
  <div className="space-y-4">
    <Skeleton className="h-24 w-full rounded-xl" />
    <Skeleton className="h-[320px] w-full rounded-xl" />
  </div>
);

/** `ancla` solo la entiende Administración; las demás vistas la ignoran. */
const VIEWS: Record<string, React.ComponentType<{ ancla?: string }>> = {
  observabilidad: dynamic(() => import("./_components/observabilidad-view"), { loading }),
  ejecuciones: dynamic(() => import("./_components/ejecuciones-view"), { loading }),
  calidad: dynamic(() => import("./_components/calidad-datos-view"), { loading }),
  etiquetado: dynamic(() => import("./_components/active-learning-view"), { loading }),
  administracion: dynamic(() => import("./_components/administracion-view"), { loading }),
};

const SPACE = CONSOLE_SPACES.find((space) => space.key === "ops")!;

const FUSIONADAS = new Map((VISTAS_FUSIONADAS.ops ?? []).map((vista) => [vista.key, vista]));

/** Un recuento solo se enseña cuando hay algo esperando: el cero es ruido. */
function contador(n: number | undefined, mas = false): string | undefined {
  return n ? `${formatNumber(n)}${mas ? "+" : ""}` : undefined;
}

export default function OpsPage() {
  const params = useSearchParams();
  const { isAdmin } = useSession();
  const { view, setView } = useSpaceView(SPACE);

  // Un `?vista=flags` o `?vista=webhooks` de antes: se monta la vista donde
  // viven hoy y se aterriza en su sección, en vez de caer a la vista por
  // defecto en silencio.
  const fusionada = FUSIONADAS.get(params.get("vista") ?? "");
  const effective = fusionada?.en ?? view;
  const View = VIEWS[effective] ?? VIEWS.observabilidad;

  // Lo que hay esperando dentro de cada vista se veía solo entrando en ella.
  // Las dos consultas son de administrador y comparten caché con su vista.
  const ejecuciones = useEjecuciones({ enabled: isAdmin });
  const pendientes = usePendientesDeAcceso({ enabled: isAdmin });
  const viewBadges: Record<string, React.ReactNode> = {};
  const rotos = contador(ejecuciones.data?.pasos_en_error);
  const esperando = contador(pendientes.total, pendientes.truncado);
  if (rotos) viewBadges.ejecuciones = rotos;
  if (esperando) viewBadges.administracion = esperando;

  return (
    <SpaceShell spaceKey="ops" view={effective} onViewChange={setView} viewBadges={viewBadges}>
      <OpsHealthStrip />
      <View ancla={fusionada?.ancla} />
    </SpaceShell>
  );
}
