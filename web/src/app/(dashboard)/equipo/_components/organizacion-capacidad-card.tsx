"use client";

/**
 * Perfil de capacidad de la organización (S2.2).
 *
 * Lo que se declara aquí es contra lo que el checklist de una oportunidad
 * contrasta el pliego. Por eso la tarjeta abre diciendo **qué falta**: cada
 * familia vacía es una familia que el go/no-go va a responder «desconocido»,
 * y sin ese aviso nadie relaciona una cosa con la otra.
 *
 * Es dato corporativo: pertenece a la organización, no a quien lo teclea. Ni
 * viaja en el export GDPR de un usuario ni se borra con su cuenta.
 */

import * as React from "react";
import { toast } from "sonner";
import { Aviso, Panel, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  CAMPO_LABELS,
  type OrganizationCapabilitiesIn,
  useOrganizationCapabilities,
  useSaveOrganizationCapabilities,
} from "../_hooks/use-organization-capacidad";
import { getErrorMessage } from "@/lib/query-feedback";
import {
  type Certificacion,
  type Facturacion,
  type PerfilEquipo,
  type Referencia,
  Seccion,
  filaCertificacion,
  filaFacturacion,
  filaPerfil,
  filaReferencia,
} from "./organizacion-capacidad-filas";

type Borrador = {
  certificaciones: Certificacion[];
  facturacion: Facturacion[];
  referencias: Referencia[];
  perfiles_equipo: PerfilEquipo[];
};

const VACIO: Borrador = {
  certificaciones: [],
  facturacion: [],
  referencias: [],
  perfiles_equipo: [],
};

export function OrganizacionCapacidadCard({
  organizationId,
  canManage,
}: {
  organizationId: number;
  canManage: boolean;
}) {
  const capacidad = useOrganizationCapabilities(organizationId);
  const guardar = useSaveOrganizationCapabilities(organizationId);
  const [borrador, setBorrador] = React.useState<Borrador | null>(null);

  const persistido = React.useMemo<Borrador>(() => {
    const datos = capacidad.data;
    if (!datos) return VACIO;
    return {
      certificaciones: datos.certificaciones ?? [],
      facturacion: datos.facturacion ?? [],
      referencias: datos.referencias ?? [],
      perfiles_equipo: datos.perfiles_equipo ?? [],
    };
  }, [capacidad.data]);

  const valores = borrador ?? persistido;
  const sucio = JSON.stringify(valores) !== JSON.stringify(persistido);
  const faltan = capacidad.data?.campos_incompletos ?? [];
  const anioActual = new Date().getFullYear();

  const submit = async () => {
    try {
      await guardar.mutateAsync(valores as OrganizationCapabilitiesIn);
      setBorrador(null);
      toast.success("Perfil de capacidad guardado");
    } catch (error) {
      toast.error(getErrorMessage(error, "accion"));
    }
  };

  return (
    <Panel>
      <PanelTitle title="Perfil de capacidad" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Con qué puede acreditarse la organización. Es lo que el checklist de cada oportunidad contrasta con el
        pliego, así que lo que no esté aquí saldrá allí como «desconocido».
      </p>
      <div className="space-y-5">
        {capacidad.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <>
            {faltan.length > 0 && (
              <Aviso tone="warning" role="note">
                <p>El go/no-go responderá «desconocido» en estas familias hasta que las rellenes:</p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {faltan.map((campo) => (
                    <Badge key={campo} variant="outline" size="sm">
                      {CAMPO_LABELS[campo]}
                    </Badge>
                  ))}
                </div>
              </Aviso>
            )}

            <Seccion<Certificacion>
              titulo="Certificaciones"
              ayuda="ISO, ENS, partner de fabricante, títulos del equipo. El ámbito importa: una certificación de empresa no acredita un título que el pliego exige a una persona."
              filas={valores.certificaciones}
              nueva={() => ({ nombre: "", ambito: "company", vigente_hasta: null })}
              onChange={(filas) => setBorrador({ ...valores, certificaciones: filas })}
              editable={canManage}
              render={(fila, actualizar) => filaCertificacion(fila, actualizar, canManage)}
            />
            <Separator />

            <Seccion<Facturacion>
              titulo="Facturación anual"
              ayuda="Los tres últimos ejercicios cerrados. La solvencia económica se mide por el mejor de los tres, que es como lo pide la LCSP."
              filas={valores.facturacion}
              nueva={() => ({ ejercicio: anioActual - 1, importe_eur: 0 })}
              onChange={(filas) => setBorrador({ ...valores, facturacion: filas })}
              editable={canManage}
              render={(fila, actualizar) => filaFacturacion(fila, actualizar, canManage)}
            />
            <Separator />

            <Seccion<Referencia>
              titulo="Referencias de contratos"
              ayuda="Trabajos ejecutados que acreditan solvencia técnica. También alimentan la afinidad del Radar de quien no tiene perfil personal."
              filas={valores.referencias}
              nueva={() => ({
                organo: "",
                anio: anioActual - 1,
                importe_eur: null,
                tecnologia: null,
                expediente_id: null,
              })}
              onChange={(filas) => setBorrador({ ...valores, referencias: filas })}
              editable={canManage}
              render={(fila, actualizar) => filaReferencia(fila, actualizar, canManage)}
            />
            <Separator />

            <Seccion<PerfilEquipo>
              titulo="Perfiles de equipo"
              ayuda="Roles disponibles en plantilla, con años de experiencia y cuántas personas de cada uno."
              filas={valores.perfiles_equipo}
              nueva={() => ({ rol: "", anios: 0, cantidad: 1 })}
              onChange={(filas) => setBorrador({ ...valores, perfiles_equipo: filas })}
              editable={canManage}
              render={(fila, actualizar) => filaPerfil(fila, actualizar, canManage)}
            />

            {canManage && sucio && (
              <Button type="button" size="sm" onClick={submit} disabled={guardar.isPending}>
                {guardar.isPending ? "Guardando…" : "Guardar perfil"}
              </Button>
            )}
            {!canManage && (
              <p className="text-tf-meta text-muted-foreground">
                Solo el propietario o un administrador pueden cambiar el perfil.
              </p>
            )}
          </>
        )}
      </div>
    </Panel>
  );
}
