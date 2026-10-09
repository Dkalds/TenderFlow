"use client";

/**
 * Estado — si la API y lo que hay debajo responden (SRE).
 *
 * El módulo conserva el nombre de la ruta que absorbió (`/observabilidad`
 * redirige a `?vista=observabilidad`); la pestaña se llama «Estado», que es la
 * pregunta que contesta.
 *
 * Este fichero es sólo el orden de la pantalla. Los datos salen de
 * `_hooks/use-observabilidad.ts` y cada bloque vive en `observabilidad/`, con
 * la lectura del payload de health —que es lo único puro y lo único que se
 * puede probar sin montar nada— en `observabilidad/health-checks.ts`.
 *
 * El veredicto se da una vez, en la cabecera. La cola de errores no se repite
 * aquí: está en la tira de salud, encima de todas las vistas, y se trabaja en
 * Ejecuciones.
 */

import { EnlaceIr } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { useSession } from "@/lib/auth";
import { useObservabilidad } from "../_hooks/use-observabilidad";
import { ComponentesGrid } from "./observabilidad/componentes-grid";
import { ErroresNavegadorCard } from "./observabilidad/errores-navegador-card";
import { EstadoSistemaCard } from "./observabilidad/estado-sistema-card";
import { GrafanaCard } from "./observabilidad/grafana-card";
import { SaludKpis } from "./observabilidad/salud-kpis";

export default function ObservabilidadView() {
  const { isAdmin } = useSession();
  const { health, isLoading, isError, isFetching, refetch, lastCheck, estado, componentes } =
    useObservabilidad();

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="sr-only">Estado</h1>
          <p className="text-tf-meta text-muted-foreground">
            Si la API y sus servicios responden. Si el dato llega completo se mira en{" "}
            <EnlaceIr href="/ops?vista=calidad" className="inline-flex">
              Datos
            </EnlaceIr>
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refetch} disabled={isFetching}>
          {isFetching ? "Refrescando…" : "Refrescar"}
        </Button>
      </div>

      <SaludKpis estado={estado} componentes={componentes} lastCheck={lastCheck} />

      <ComponentesGrid componentes={componentes} />

      {isAdmin && <ErroresNavegadorCard />}

      <EstadoSistemaCard health={health} isLoading={isLoading} isError={isError} />

      <GrafanaCard />
    </div>
  );
}
