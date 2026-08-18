"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { CONSOLE_SPACES } from "@/lib/console-spaces";
import { OpsHealthStrip } from "./_components/health-strip";

/**
 * Ops y Admin — las seis rutas internas bajo una sola puerta.
 *
 * `/observabilidad`, `/calidad-datos`, `/administracion`, `/feature-flags`,
 * `/active-learning` y `/webhooks` son el mismo turno de guardia: saber si el
 * dato llega, si es bueno y quién puede tocar qué. Antes había que entrar en
 * dos pantallas distintas para saber si el DLQ tenía cola. Las 41 funciones
 * inventariadas siguen intactas; cada vista monta su pantalla original
 * completa, con su propia guarda de administrador donde la tenía.
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
  observabilidad: dynamic(() => import("./_components/observabilidad-view"), { loading }),
  calidad: dynamic(() => import("./_components/calidad-datos-view"), { loading }),
  administracion: dynamic(() => import("./_components/administracion-view"), { loading }),
  flags: dynamic(() => import("./_components/feature-flags-view"), { loading }),
  etiquetado: dynamic(() => import("./_components/active-learning-view"), { loading }),
  webhooks: dynamic(() => import("./_components/webhooks-view"), { loading }),
};

const SPACE = CONSOLE_SPACES.find((space) => space.key === "ops")!;

export default function OpsPage() {
  const { view, setView } = useSpaceView(SPACE);
  const View = VIEWS[view] ?? VIEWS.observabilidad;

  return (
    <SpaceShell spaceKey="ops" view={view} onViewChange={setView}>
      <OpsHealthStrip />
      <View />
    </SpaceShell>
  );
}
