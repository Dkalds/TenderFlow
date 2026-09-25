"use client";

/**
 * Aviso de cobertura de la resolución de entidades, junto a las cuotas.
 *
 * Las cuotas, el HHI y el top de esta pantalla reparten lo adjudicado entre
 * empresas. Lo que el maestro no ha resuelto sólo se junta con su empresa si
 * coincide el NIF o el nombre normalizado, así que con poca cobertura una misma
 * empresa puede quedar partida en varias filas. Hasta 2026-09-25 el aviso sólo
 * salía en Empresas, que es donde se arregla, y no aquí, que es donde se nota.
 *
 * Sin dato, o con la cobertura por encima del umbral, no pinta nada. Es una
 * advertencia, no un indicador de estado.
 */

import Link from "next/link";
import { TriangleAlert } from "lucide-react";

import { UMBRAL_IMPORTE_RESUELTO, importeResueltoBajoUmbral, useEmpresasStats } from "@/hooks/use-empresas-stats";
import { formatPercent } from "@/lib/utils";

export function CompetidoresResolucion() {
  const { data } = useEmpresasStats();
  if (!data || !importeResueltoBajoUmbral(data)) return null;

  return (
    <div role="note" className="border-warning/30 bg-warning/10 text-warning flex gap-3 rounded-lg border p-3 text-sm">
      <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">Cuotas aproximadas</p>
        <p className="mt-0.5 opacity-90">
          Solo el {formatPercent(data.pct_importe)} del importe adjudicado está resuelto a una empresa del maestro, y el
          umbral es el {formatPercent(UMBRAL_IMPORTE_RESUELTO, 0)}. Mientras no llegue, una misma empresa puede aparecer
          repartida en varias filas, con menos cuota de la que tiene.
        </p>
      </div>
      <Link
        href="/empresas?vista=revision"
        className="shrink-0 self-center font-medium underline-offset-4 hover:underline"
      >
        Revisar en Empresas
      </Link>
    </div>
  );
}
