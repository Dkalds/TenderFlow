"use client";

import { Suspense } from "react";
import { ConsoleRail } from "@/components/layout/console-rail";
import { ScopeBar } from "@/components/layout/scope-bar";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { ScrollEdgeProvider } from "@/components/layout/scroll-edge";

/**
 * Marco del dashboard — rail de 56px + barra de ámbito de 52px.
 *
 * Antes se apilaban seis bandas de cromo antes de la primera fila de dato
 * (TopNav + KpiBar + FilterBar + Breadcrumb + PageTabs + PageHeader). Ahora
 * son dos, y ninguna capacidad se ha perdido por el camino:
 *
 * - La navegación de la sidebar vive en el rail (`console-rail.tsx`), que
 *   cubre los 14 espacios.
 * - Buscar (⌘K), exportar, notificaciones, densidad, tema, organización activa
 *   y cerrar sesión — todo lo que estaba en el TopNav — vive en la barra de
 *   ámbito y en el menú de cuenta del rail.
 * - Los filtros globales son ahora el objeto de ámbito (`scope-bar.tsx`), con
 *   el mismo contrato por página y los mismos seis controles.
 *
 * La rama de cromo heredado (KPI bar + breadcrumb + pestañas de sección) se
 * retiró al quedar construidos los 14 espacios (`BUILT_SPACE_ROUTES`): toda
 * ruta renderizable es superficie de consola — las heredadas redirigen por
 * `next.config` a su `?vista=` y nunca llegan a pintar cromo.
 */
export function ConsoleFrame({ children }: { children: React.ReactNode }) {
  return (
    // El proveedor del borde de scroll envuelve el marco entero porque el
    // contenedor que scrollea (`DashboardShell`) y el cromo que dibuja el borde
    // (rail móvil y barra de ámbito) son hermanos, no antepasados.
    <ScrollEdgeProvider>
      <div className="flex min-h-screen bg-background text-foreground">
        <ConsoleRail />

        <div className="flex min-h-screen min-w-0 flex-1 flex-col">
          {/* El hueco de carga tampoco lleva borde: el estado inicial es "en el
              tope", y ahí no hay nada debajo que separar. */}
          <Suspense fallback={<div className="h-[52px] flex-none" />}>
            <ScopeBar />
          </Suspense>

          {/* La pantalla gobierna su propio espacio, sin contenedor centrado ni
              relleno — la tabla llega hasta el borde. */}
          <DashboardShell>
            <Suspense fallback={null}>{children}</Suspense>
          </DashboardShell>
        </div>
      </div>
    </ScrollEdgeProvider>
  );
}
