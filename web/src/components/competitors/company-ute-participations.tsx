"use client";

import Link from "next/link";

import { Aviso, Panel, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { formatCurrency, formatNumber } from "@/lib/utils";

import type { CompanyUteParticipation } from "./company-profile-types";

/**
 * Participaciones en UTE del dossier de competidor.
 *
 * El backend devuelve estas filas fuera de `totales`/`posicion_mercado` a
 * propósito: lo adjudicado a la UTE ya se contabiliza bajo la UTE, que es una
 * empresa propia del maestro. La sección existe para que ese volumen deje de
 * ser invisible, pero toda la copy está escrita para impedir la lectura
 * equivocada: son importes **adicionales**, nunca un desglose de los totales
 * de arriba, y sumarlos duplicaría el dinero.
 */
export function CompanyUteParticipations({
  participations,
  companyName,
}: {
  participations: CompanyUteParticipation[];
  companyName: string;
}) {
  if (!participations.length) return null;

  return (
    <Panel className="p-0">
      <div className="px-4 pt-3.5">
        <PanelTitle title="Participación en UTEs" className="mb-1" />
        <p className="mb-3 text-tf-meta text-muted-foreground">
          {formatNumber(participations.length)} {participations.length === 1 ? "unión temporal" : "uniones temporales"}{" "}
          en las que {companyName} figura como miembro. Cada UTE es una empresa propia del registro y lo adjudicado va a
          su nombre.
        </p>
      </div>
      <Aviso
        tone="warning"
        role="note"
        variant="banda"
        className="border-t"
        title="Importes adicionales, no un desglose de los totales"
      >
        Nada de lo que aparece aquí está incluido en el importe adjudicado, las adjudicaciones ni la cuota de{" "}
        {companyName}: el mercado ya lo contabiliza bajo la UTE. Añadirlo a las cifras de arriba contaría el mismo
        dinero dos veces.
      </Aviso>

      <ul className="divide-y divide-border/60">
          {participations.map((participation) => (
            <li key={participation.ute_empresa_id} className="px-4 py-3.5">
              <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                <div className="min-w-0 flex-1">
                  {/* El `title` repetía palabra por palabra el texto del
                      enlace, que no está truncado: no aportaba nada y encima
                      era inalcanzable con teclado. */}
                  <Link
                    href={`/competencia/empresa/${participation.ute_empresa_id}`}
                    className="text-tf-body font-medium transition-colors hover:text-primary"
                  >
                    {participation.ute_nombre}
                  </Link>
                  {participation.otros_miembros.length ? (
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <span className="text-tf-meta text-muted-foreground">Otros miembros:</span>
                      {participation.otros_miembros.map((miembro) => (
                        <Badge key={miembro} variant="secondary" size="sm">
                          {miembro}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-2 text-tf-meta text-muted-foreground">Sin otros miembros identificados</p>
                  )}
                </div>
                <div className="shrink-0 text-right">
                  <p className="font-semibold">{formatCurrency(participation.importe_total)}</p>
                  <p className="mt-0.5 text-tf-meta text-muted-foreground">
                    {formatNumber(participation.contratos)}{" "}
                    {participation.contratos === 1 ? "adjudicación" : "adjudicaciones"} de la UTE
                  </p>
                </div>
              </div>
            </li>
          ))}
        </ul>

      <p className="border-t border-border/60 px-4 py-3 text-tf-meta text-muted-foreground">
        Los totales del dossier miden solo lo adjudicado directamente a {companyName}. Para el alcance completo,
        léelos junto a esta sección, no sumados con ella.
      </p>
    </Panel>
  );
}
