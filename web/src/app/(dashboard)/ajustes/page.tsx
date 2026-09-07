"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { CONSOLE_SPACES } from "@/lib/console-spaces";

/**
 * Ajustes — todo lo que se configura, en un sitio (C7.5).
 *
 * Antes estaba repartido: el tema sólo desde la paleta de comandos, la
 * organización activa desde la barra superior, los derechos RGPD en
 * `/mi-cuenta`, y las sesiones, las claves de API y las preferencias de
 * notificación **en ningún sitio** — sus endpoints existían desde el stream C2
 * y no tenían pantalla.
 *
 * Consolidar no elimina **funcionalidad**: `/mi-cuenta` desaparece como ruta
 * —su `page.tsx` habría quedado a la sombra de su propio 308 y no se
 * ejecutaría nunca, que es lo que prohíbe el test de títulos— y su contenido
 * entero vive como `?vista=cuenta`. El enlace viejo sigue llevando ahí.
 */

const loading = () => <Skeleton className="h-[320px] w-full rounded-xl" />;

const VIEWS: Record<string, React.ComponentType> = {
  apariencia: dynamic(() => import("./_components/apariencia-view"), { loading }),
  organizacion: dynamic(() => import("./_components/organizacion-view"), { loading }),
  notificaciones: dynamic(() => import("./_components/notificaciones-view"), { loading }),
  sesiones: dynamic(() => import("./_components/sesiones-view"), { loading }),
  claves: dynamic(() => import("./_components/claves-view"), { loading }),
  cuenta: dynamic(() => import("./_components/cuenta-view"), { loading }),
};

const SPACE = CONSOLE_SPACES.find((space) => space.key === "ajustes")!;

export default function AjustesPage() {
  const { view, setView } = useSpaceView(SPACE);
  const View = VIEWS[view] ?? VIEWS.apariencia;

  return (
    <SpaceShell spaceKey="ajustes" view={view} onViewChange={setView}>
      <div className="w-full max-w-3xl">
        <View />
      </div>
    </SpaceShell>
  );
}
