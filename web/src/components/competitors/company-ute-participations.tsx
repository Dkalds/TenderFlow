"use client";

import Link from "next/link";
import { Info, Users } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Users className="text-primary h-4 w-4" aria-hidden="true" />
          Participación en UTEs
        </CardTitle>
        <CardDescription>
          {formatNumber(participations.length)} {participations.length === 1 ? "unión temporal" : "uniones temporales"}{" "}
          en las que {companyName} figura como miembro. Cada UTE es una empresa propia del registro y lo adjudicado va a
          su nombre.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <div className="border-warning/30 bg-warning/10 flex gap-3 border-y px-5 py-3.5" role="note">
          <Info className="text-warning mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div className="text-sm leading-6">
            <p className="font-semibold">Importes adicionales, no un desglose de los totales</p>
            <p className="text-muted-foreground mt-0.5">
              Nada de lo que aparece aquí está incluido en el importe adjudicado, las adjudicaciones ni la cuota de{" "}
              {companyName}: el mercado ya lo contabiliza bajo la UTE. Añadirlo a las cifras de arriba contaría el mismo
              dinero dos veces.
            </p>
          </div>
        </div>

        <ul className="divide-y">
          {participations.map((participation) => (
            <li key={participation.ute_empresa_id} className="px-5 py-4">
              <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                <div className="min-w-0 flex-1">
                  {/* El `title` repetía palabra por palabra el texto del
                      enlace, que no está truncado: no aportaba nada y encima
                      era inalcanzable con teclado. */}
                  <Link
                    href={`/competidores/empresa/${participation.ute_empresa_id}`}
                    className="hover:text-primary text-sm font-medium hover:underline"
                  >
                    {participation.ute_nombre}
                  </Link>
                  {participation.otros_miembros.length ? (
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <span className="text-muted-foreground text-xs">Otros miembros:</span>
                      {participation.otros_miembros.map((miembro) => (
                        <Badge key={miembro} variant="secondary" className="font-normal">
                          {miembro}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    <p className="text-muted-foreground mt-2 text-xs">Sin otros miembros identificados</p>
                  )}
                </div>
                <div className="shrink-0 text-right">
                  <p className="font-semibold tabular-nums">{formatCurrency(participation.importe_total)}</p>
                  <p className="text-muted-foreground mt-0.5 text-xs tabular-nums">
                    {formatNumber(participation.contratos)}{" "}
                    {participation.contratos === 1 ? "adjudicación" : "adjudicaciones"} de la UTE
                  </p>
                </div>
              </div>
            </li>
          ))}
        </ul>

        <p className="text-muted-foreground border-t px-5 py-3 text-xs leading-5">
          Los totales del dossier miden solo lo adjudicado directamente a {companyName}. Para el alcance completo,
          léelos junto a esta sección, no sumados con ella.
        </p>
      </CardContent>
    </Card>
  );
}
