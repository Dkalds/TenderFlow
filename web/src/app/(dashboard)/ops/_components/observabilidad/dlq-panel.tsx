"use client";

/**
 * Recuento de la cola de errores, con la salida hacia Calidad de datos.
 *
 * Aquí sólo se cuenta. La inspección entrada a entrada y el reencolado viven en
 * Administración (`DlqCard`, sobre `/admin/dlq`); este panel enlaza allí en vez
 * de tener un botón de reintento propio, que durante meses sólo respondía
 * «Funcionalidad en desarrollo».
 */

import Link from "next/link";
import { Aviso, Panel, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { formatNumber } from "@/lib/utils";

export function DlqPanel({ dlqCount }: { dlqCount: number }) {
  const hayCola = dlqCount > 0;

  return (
    <Panel>
      <PanelTitle title="Cola de errores (DLQ)" />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="tf-tnum text-tf-title font-semibold">{formatNumber(dlqCount)}</p>
          <p className="text-tf-meta text-muted-foreground">registros pendientes de reprocesar</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button asChild variant="outline" size="sm">
            <Link href="/ops?vista=calidad">Calidad de datos</Link>
          </Button>
          <Button asChild variant="outline" size="sm">
            <Link href="/ops?vista=administracion">Inspeccionar y reencolar</Link>
          </Button>
        </div>
      </div>
      {hayCola && (
        <Aviso tone="warning" className="mt-3">
          Hay registros en la cola: revísalos y reencólalos desde Administración.
        </Aviso>
      )}
    </Panel>
  );
}
