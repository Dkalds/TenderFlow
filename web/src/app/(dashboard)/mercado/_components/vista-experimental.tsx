"use client";

/**
 * Envoltorio de las dos vistas `experimental` de Mercado (Clusters y Proyectos
 * y módulos). Lee la misma flag que `mercado/page.tsx`, que la usa para marcar
 * la pestaña del conmutador como apagada antes de que nadie la pulse.
 *
 * # Qué hace
 *
 * 1. **Marca** la vista en su propia superficie. El conmutador de `SpaceShell`
 *    ya pinta el distintivo «Exp» en la pestaña, pero a estas dos vistas se
 *    llega también por URL directa y por el 308 de la ruta heredada
 *    (`/clusters`, `/proyectos-modulos`), donde no hay pestaña que mirar.
 * 2. **Obedece un `no` explícito.** Con la flag apagada desde `/ops`, la vista
 *    no se monta y se dice por qué.
 * 3. **No obedece un silencio.** Sin API de flags —o con la flag aún sin
 *    fila— la vista sigue visible y marcada: el fail-open vive en
 *    `useFeatureFlag`, y este componente sólo lo respeta.
 *
 * # Por qué la telemetría se emite aquí
 *
 * `espacio_abierto` mide el clic en la pestaña del conmutador, no que la vista
 * llegue a montarse. Lo que decide si una superficie en validación se gradúa o
 * se retira es lo segundo, así que el evento sale del montaje real, con el
 * régimen (`activo` / `sin_respuesta`) bajo el que se pintó.
 */

import * as React from "react";
import { FlaskConical } from "lucide-react";

import { Aviso, Panel, PanelEmpty } from "@/components/console/panel";
import { useFeatureFlag } from "@/hooks/use-feature-flag";
import { registrarEvento } from "@/lib/analytics";

export interface VistaExperimentalProps {
  /** Nombre de la fila de `feature_flags` que gobierna esta vista. */
  flag: string;
  /** Clave de la vista en `lib/space-views.ts`. Viaja a la telemetría. */
  vista: string;
  /** Qué se está validando, en una frase. Se muestra junto a la marca. */
  descripcion: string;
  children: React.ReactNode;
}

export function VistaExperimental({
  flag,
  vista,
  descripcion,
  children,
}: VistaExperimentalProps) {
  const { enabled, estado } = useFeatureFlag(flag);

  React.useEffect(() => {
    if (!enabled) return;
    // `inactivo` no puede llegar aquí: con la flag apagada no hay vista abierta.
    registrarEvento("vista_experimental_abierta", {
      vista,
      flag: estado === "activo" ? "activo" : "sin_respuesta",
    });
  }, [enabled, estado, vista]);

  if (!enabled) {
    return (
      <Panel>
        <PanelEmpty
          icon={FlaskConical}
          title="Vista desactivada"
          hint={
            <>
              Esta vista experimental está apagada para tu organización. Se enciende
              en Ops › Administración (<code className="font-mono">{flag}</code>).
            </>
          }
        />
      </Panel>
    );
  }

  return (
    <div className="space-y-4">
      {/* `note` y no `status`: es una marca fija de la vista, no un cambio de
          estado que el lector tenga que anunciar al montarse. */}
      <Aviso tone="warning" icon={FlaskConical} role="note" title="Vista experimental">
        {descripcion} En validación: puede cambiar o desaparecer.
      </Aviso>
      {children}
    </div>
  );
}
