"use client";

/**
 * Ejecuciones — qué pasó con lo que corre solo.
 *
 * Tres bloques, de lo programado a lo que falló y espera a una persona: los
 * pasos del cierre post-ingesta, la cola de trabajo a demanda y la cola de
 * errores de la ingesta (que antes vivía en Administración, entre los usuarios
 * y las claves, y se anunciaba desde otros tres sitios).
 *
 * La guarda de administrador viaja con la vista (ver la nota en
 * `administracion-view.tsx`): las tres consultas son de `/admin/*`.
 */

import { PanelError } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { AdminGuard } from "@/components/admin-guard";
import { useEjecuciones } from "../_hooks/use-ejecuciones";
import { DlqCard } from "./ejecuciones/dlq-card";
import { PasosCard } from "./ejecuciones/pasos-card";
import { TrabajosCard } from "./ejecuciones/trabajos-card";

export default function EjecucionesView() {
  return (
    <AdminGuard>
      <EjecucionesContent />
    </AdminGuard>
  );
}

function EjecucionesContent() {
  const { data, isLoading, error, refetch } = useEjecuciones();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="sr-only">Ejecuciones</h1>
        <p className="text-tf-meta text-muted-foreground">
          Lo que corre tras cada ingesta, lo que piden los usuarios y lo que falló y espera a alguien.
        </p>
      </div>

      {/* Con la consulta caída no se pinta ninguna tabla: una tabla vacía
          afirmaría que no hay pasos, que es otra cosa. */}
      {error ? (
        <PanelError title="No se pudieron cargar las ejecuciones" error={error} onRetry={() => void refetch()} />
      ) : isLoading || !data ? (
        <div className="space-y-4">
          <Skeleton className="h-[420px] w-full rounded-xl" />
          <Skeleton className="h-32 w-full rounded-xl" />
        </div>
      ) : (
        <>
          <PasosCard resumen={data} />
          <TrabajosCard resumen={data} />
        </>
      )}

      <DlqCard />
    </div>
  );
}
