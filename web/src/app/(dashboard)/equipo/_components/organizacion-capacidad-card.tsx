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
import { Loader2, Save } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  CAMPO_LABELS,
  type OrganizationCapabilitiesIn,
  useOrganizationCapabilities,
  useSaveOrganizationCapabilities,
} from "../_hooks/use-organization-capacidad";
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
      toast.error(error instanceof Error ? error.message : "No se pudo guardar el perfil");
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Perfil de capacidad</CardTitle>
        <CardDescription>
          Con qué puede acreditarse la organización. Es lo que el checklist de cada oportunidad
          contrasta contra el pliego, así que lo que no esté aquí saldrá allí como «desconocido».
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {capacidad.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <>
            {faltan.length > 0 && (
              <div className="space-y-2 rounded-lg border border-dashed border-border bg-muted/30 p-3">
                <p className="text-sm text-muted-foreground">
                  El go/no-go responderá «desconocido» en estas familias hasta que las rellenéis:
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {faltan.map((campo) => (
                    <Badge key={campo} variant="outline">
                      {CAMPO_LABELS[campo]}
                    </Badge>
                  ))}
                </div>
              </div>
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
                {guardar.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
                Guardar perfil
              </Button>
            )}
            {!canManage && (
              <p className="text-sm text-muted-foreground">
                Solo el propietario o un administrador pueden cambiar el perfil.
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
