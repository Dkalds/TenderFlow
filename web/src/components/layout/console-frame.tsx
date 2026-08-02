"use client";

import { Suspense } from "react";
import { usePathname } from "next/navigation";
import { ConsoleRail } from "@/components/layout/console-rail";
import { ScopeBar } from "@/components/layout/scope-bar";
import { Breadcrumb } from "@/components/layout/breadcrumb";
import { PageTabs } from "@/components/layout/page-tabs";
import { KpiBarConnected } from "@/components/layout/kpi-bar";
import { DashboardShell } from "@/components/layout/dashboard-shell";
import { isConsoleRoute } from "@/lib/console-spaces";

/**
 * Marco del dashboard — rail de 56px + barra de ámbito de 52px.
 *
 * Antes se apilaban seis bandas de cromo antes de la primera fila de dato
 * (TopNav + KpiBar + FilterBar + Breadcrumb + PageTabs + PageHeader). Ahora
 * son dos, y ninguna capacidad se ha perdido por el camino:
 *
 * - La navegación de la sidebar vive en el rail (`console-rail.tsx`), que
 *   cubre los 14 espacios y, mientras un espacio no esté construido, enlaza a
 *   la ruta heredada que absorberá.
 * - Buscar (⌘K), exportar, notificaciones, densidad, tema, organización activa
 *   y cerrar sesión — todo lo que estaba en el TopNav — vive en la barra de
 *   ámbito y en el menú de cuenta del rail.
 * - Los filtros globales son ahora el objeto de ámbito (`scope-bar.tsx`), con
 *   el mismo contrato por página y los mismos seis controles.
 *
 * Las pantallas que aún no se han rediseñado (`isConsoleRoute` en falso)
 * conservan el KPI bar, el breadcrumb y las pestañas de sección: quitárselos
 * antes de que su espacio exista sería perder navegación real.
 */
export function ConsoleFrame({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const consoleSurface = isConsoleRoute(pathname);

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <ConsoleRail />

      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <Suspense fallback={<div className="h-[52px] flex-none border-b border-border/70" />}>
          <ScopeBar />
        </Suspense>

        {consoleSurface ? (
          // Superficie de consola: la pantalla gobierna su propio espacio, sin
          // contenedor centrado ni relleno — la tabla llega hasta el borde.
          <DashboardShell>
            <Suspense fallback={null}>{children}</Suspense>
          </DashboardShell>
        ) : (
          <>
            <KpiBarConnected />
            <DashboardShell>
              <div className="mx-auto w-full max-w-[1640px] px-4 py-5 sm:px-6 lg:px-8">
                <Breadcrumb />
                <PageTabs />
                <div className="mt-4">
                  <Suspense fallback={null}>{children}</Suspense>
                </div>
              </div>
            </DashboardShell>
          </>
        )}
      </div>
    </div>
  );
}
