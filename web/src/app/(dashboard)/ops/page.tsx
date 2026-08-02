"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { CONSOLE_SPACES } from "@/lib/console-spaces";

/**
 * Ops y Admin — las cinco rutas internas bajo una sola puerta.
 *
 * `/observabilidad`, `/calidad-datos`, `/administracion`, `/feature-flags` y
 * `/active-learning` son el mismo turno de guardia: saber si el dato llega,
 * si es bueno y quién puede tocar qué. Antes había que entrar en dos pantallas
 * distintas para saber si el DLQ tenía cola. Las 41 funciones inventariadas
 * siguen intactas; cada vista monta su pantalla original completa, con su
 * propia guarda de administrador donde la tenía.
 */

const loading = () => (
  <div className="space-y-4">
    <Skeleton className="h-24 w-full rounded-xl" />
    <Skeleton className="h-[320px] w-full rounded-xl" />
  </div>
);

const VIEWS: Record<string, React.ComponentType> = {
  observabilidad: dynamic(() => import("../observabilidad/page"), { loading }),
  calidad: dynamic(() => import("../calidad-datos/page"), { loading }),
  administracion: dynamic(() => import("../administracion/page"), { loading }),
  flags: dynamic(() => import("../feature-flags/page"), { loading }),
  etiquetado: dynamic(() => import("../active-learning/page"), { loading }),
};

const SPACE = CONSOLE_SPACES.find((space) => space.key === "ops")!;

export default function OpsPage() {
  const { view, setView } = useSpaceView(SPACE);
  const View = VIEWS[view] ?? VIEWS.observabilidad;

  return (
    <SpaceShell spaceKey="ops" view={view} onViewChange={setView}>
      <View />
    </SpaceShell>
  );
}
