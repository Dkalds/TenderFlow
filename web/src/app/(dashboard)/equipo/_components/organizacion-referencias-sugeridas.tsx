"use client";

/**
 * Contratos que la organización ganó en los últimos tres años y aún no ha
 * declarado como referencia (`referencias_sugeridas` de
 * `GET /organizations/{id}/capabilities`, a partir de sus NIF).
 *
 * Se proponen, no se guardan: lo adjudicado no es lo ejecutado —un acuerdo
 * marco publica su valor máximo— y solo la organización sabe qué contratos
 * puede certificar. «Añadir» los pasa al borrador; se guardan con el resto
 * del perfil.
 */

import { Plus } from "lucide-react";
import { ROTULO_DATO } from "@/components/console/panel";
import { EnlaceFicha } from "@/components/ficha/enlace-ficha";
import { Button } from "@/components/ui/button";
import { formatCurrency } from "@/lib/utils";
import type { Referencia } from "./organizacion-capacidad-filas";

export function OrganizacionReferenciasSugeridas({
  sugeridas,
  declaradas,
  editable,
  onAnadir,
}: {
  sugeridas: Referencia[];
  /** Las del borrador: lo que ya se añadió deja de proponerse sin esperar al guardado. */
  declaradas: Referencia[];
  editable: boolean;
  onAnadir: (referencias: Referencia[]) => void;
}) {
  const ya = new Set(declaradas.map((r) => r.expediente_id).filter(Boolean));
  const pendientes = sugeridas.filter((r) => !r.expediente_id || !ya.has(r.expediente_id));
  if (pendientes.length === 0) return null;
  return (
    // Un filete y no una caja: dentro del panel, una caja con borde sería una
    // tarjeta anidada; el resto de la tarjeta se separa así.
    <div className="border-divider space-y-2 border-t pt-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-tf-body font-medium">
          {pendientes.length === 1
            ? "Un contrato ganado en los últimos tres años"
            : `${pendientes.length} contratos ganados en los últimos tres años`}
        </p>
        {editable && pendientes.length > 1 && (
          <Button type="button" size="sm" variant="outline" onClick={() => onAnadir(pendientes)}>
            Añadir todos
          </Button>
        )}
      </div>
      <p className="text-tf-meta text-muted-foreground">
        Adjudicados a tus NIF según la publicación oficial. Revisa el importe antes de usarlos como referencia: es el
        adjudicado, no el ejecutado.
      </p>
      <ul className="divide-divider divide-y">
        {pendientes.map((referencia) => (
          <li
            key={referencia.expediente_id ?? referencia.organo}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2"
          >
            <div className="min-w-0 flex-[1_1_240px]">
              <p className="text-tf-body leading-snug">{referencia.organo}</p>
              <p className="text-tf-meta text-muted-foreground">
                <span className="tf-tnum">{referencia.anio}</span>
                {referencia.tecnologia && <span> · {referencia.tecnologia}</span>}
                {referencia.expediente_id && (
                  <>
                    {" · "}
                    <EnlaceFicha idExterno={referencia.expediente_id} className="text-primary hover:underline">
                      Ver la licitación
                    </EnlaceFicha>
                  </>
                )}
              </p>
            </div>
            {referencia.importe_eur != null && (
              <span className="tf-tnum text-tf-body font-semibold">{formatCurrency(referencia.importe_eur)}</span>
            )}
            {editable && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                aria-label={`Añadir ${referencia.organo} (${referencia.anio}) a las referencias`}
                onClick={() => onAnadir([referencia])}
              >
                <Plus aria-hidden="true" />
                Añadir
              </Button>
            )}
          </li>
        ))}
      </ul>
      <p className={ROTULO_DATO}>Fuente: adjudicaciones publicadas en las plataformas de contratación</p>
    </div>
  );
}
