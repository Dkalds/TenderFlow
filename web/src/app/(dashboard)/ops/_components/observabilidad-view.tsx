"use client";

/**
 * Observabilidad — salud de infraestructura y servicios (SRE).
 *
 * El cuerpo vive aquí y no en `observabilidad/page.tsx` porque lo montan dos
 * entradas: la ruta propia y la vista `?vista=observabilidad` del espacio Ops.
 * Antes `/ops` importaba el `page.tsx` de la ruta, así que ese módulo tenía dos
 * papeles a la vez (boundary de ruta y componente) y Next no podía tratarlo
 * como lo primero.
 *
 * Este fichero es sólo el orden de la pantalla. Los datos salen de
 * `_hooks/use-observabilidad.ts` y cada bloque vive en `observabilidad/`, con
 * la lectura del payload de health —que es lo único puro y lo único que se
 * puede probar sin montar nada— en `observabilidad/health-checks.ts`.
 */

import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { useObservabilidad } from "../_hooks/use-observabilidad";
import { ComponentesGrid } from "./observabilidad/componentes-grid";
import { DlqPanel } from "./observabilidad/dlq-panel";
import { EstadoGlobalRow } from "./observabilidad/estado-global-row";
import { EstadoSistemaCard } from "./observabilidad/estado-sistema-card";
import { GrafanaCard } from "./observabilidad/grafana-card";
import { SaludKpis } from "./observabilidad/salud-kpis";

export default function ObservabilidadView() {
  const {
    health,
    isLoading,
    isError,
    isFetching,
    refetch,
    isOnline,
    lastCheck,
    estado,
    checks,
    dlqCount,
  } = useObservabilidad();

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="sr-only">Observabilidad</h1>
          <p className="text-muted-foreground">
            Salud de infraestructura y servicios (SRE). Para la integridad del
            dato (completitud, DLQ, drops de escritura) ve a{" "}
            <Link
              href="/calidad-datos"
              className="font-medium underline underline-offset-2 hover:text-foreground"
            >
              Calidad de Datos
            </Link>
            .
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={refetch}
          disabled={isFetching}
          aria-label="Refrescar estado del sistema"
        >
          <RefreshCw className={cn("mr-2 h-4 w-4", isFetching && "animate-spin")} />
          Refrescar
        </Button>
      </div>

      <SaludKpis
        isLoading={isLoading}
        isError={isError}
        isOnline={isOnline}
        lastCheck={lastCheck}
        version={health?.version}
      />

      {!isLoading && <EstadoGlobalRow estado={estado} lastCheck={lastCheck} />}

      <Separator />

      <ComponentesGrid checks={checks} />

      <EstadoSistemaCard
        health={health}
        isLoading={isLoading}
        isError={isError}
        isOnline={isOnline}
      />

      <DlqPanel dlqCount={dlqCount} />

      <GrafanaCard />
    </div>
  );
}
