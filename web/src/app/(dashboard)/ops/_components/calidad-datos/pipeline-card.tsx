"use client";

/** Cierre de la pantalla: el universo sobre el que van todos los porcentajes. */

import { Panel, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { formatNumber } from "@/lib/utils";

export interface PipelineCardProps {
  totalRecords: number | undefined;
  isLoading: boolean;
}

export function PipelineCard({ totalRecords, isLoading }: PipelineCardProps) {
  return (
    <Panel>
      <PanelTitle title="Resumen de la ingesta" hint="La base de todos los porcentajes de esta pantalla" />
      {isLoading ? (
        <Skeleton className="h-8 w-32" />
      ) : (
        <div>
          <p className="tf-tnum text-tf-title font-semibold">{formatNumber(totalRecords)}</p>
          <p className="text-tf-meta text-muted-foreground">registros en total</p>
        </div>
      )}
    </Panel>
  );
}
