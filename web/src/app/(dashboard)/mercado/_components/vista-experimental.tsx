"use client";

/**
 * Envoltorio de las dos vistas `experimental` de Mercado (Clusters y Proyectos
 * y módulos), y el único sitio del producto que lee una feature flag.
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
      <div
        role="status"
        className="rounded-xl border border-border/60 bg-card/40 p-6 text-center"
      >
        <FlaskConical className="mx-auto h-5 w-5 text-muted-foreground" aria-hidden="true" />
        <p className="mt-2 text-sm font-medium">Vista desactivada</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Esta vista experimental está apagada para tu organización. Se enciende
          desde Ops → Feature flags (<span className="font-mono">{flag}</span>).
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2">
        <FlaskConical className="mt-0.5 h-3.5 w-3.5 flex-none text-warning" aria-hidden="true" />
        <div className="min-w-0">
          <p className="text-[12px] font-semibold text-warning">Vista experimental</p>
          <p className="text-[11.5px] text-muted-foreground">
            {descripcion} En validación: puede cambiar o desaparecer.
          </p>
        </div>
      </div>
      {children}
    </div>
  );
}
