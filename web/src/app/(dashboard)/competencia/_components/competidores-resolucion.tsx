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

import { Aviso, EnlaceIr } from "@/components/console/panel";
import { UMBRAL_IMPORTE_RESUELTO, importeResueltoBajoUmbral, useEmpresasStats } from "@/hooks/use-empresas-stats";
import { formatPercent } from "@/lib/utils";

export function CompetidoresResolucion() {
  const { data } = useEmpresasStats();
  if (!data || !importeResueltoBajoUmbral(data)) return null;

  return (
    <Aviso
      tone="warning"
      role="note"
      title="Cuotas aproximadas"
      action={<EnlaceIr href="/empresas?vista=revision">Revisar en Empresas</EnlaceIr>}
    >
      Solo el {formatPercent(data.pct_importe)} del importe adjudicado está resuelto a una empresa del maestro, y el
      umbral es el {formatPercent(UMBRAL_IMPORTE_RESUELTO, 0)}. Mientras no llegue, una misma empresa puede aparecer
      repartida en varias filas, con menos cuota de la que tiene.
    </Aviso>
  );
}
