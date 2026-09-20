"use client";

/**
 * F4.1 — probabilidad de cierre por etapa, en Equipo → Organización.
 *
 * Es el supuesto con el que el backend calcula el valor ponderado del pipeline
 * (`PursuitMetrics.pipeline_value_eur`) que Mi Pipeline → Embudo enseña. Hasta
 * ahora sólo se podía leer: todas las organizaciones ponderaban con los
 * defaults de D34.
 *
 * Qué no se hace aquí, a propósito:
 * - **Las etapas no se enumeran**: salen de `probabilidades_etapa_default`, que
 *   el backend manda con la configuración. Una etapa nueva aparece sola.
 * - **Los defaults no se copian**: un campo vacío es «el valor por defecto» y
 *   no viaja en el PUT. El placeholder enseña cuál es, leído de la respuesta.
 * - **El permiso lo decide el backend** (403 si no eres owner/admin); la
 *   pantalla sólo evita ofrecer lo que va a fallar.
 */

import * as React from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, Percent, Save } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useOrganizationSettings,
  useUpdateOrganizationSettings,
} from "@/hooks/use-organization-settings";
import type { OrganizationSettingsOut } from "@/lib/api-types";
import { ariaCampo, CampoError } from "@/lib/forms/campo";
import { probabilidadesEtapa } from "@/lib/forms/esquemas";
import { numeroDeTexto } from "@/lib/forms/valores";
import { etiquetaEtapa, ordenarEtapas } from "@/lib/pipeline-ponderado";

interface ValoresProbabilidades {
  probabilidades_etapa: Record<string, string>;
}

/** Lo guardado como valores de formulario: vacío donde manda el default. */
export function valoresDeAjustes(ajustes: OrganizationSettingsOut, etapas: readonly string[]) {
  const guardadas = ajustes.probabilidades_etapa ?? {};
  return {
    probabilidades_etapa: Object.fromEntries(
      etapas.map((etapa) => [etapa, guardadas[etapa] != null ? String(guardadas[etapa]) : ""]),
    ),
  };
}

/** Del formulario al contrato: sólo las etapas con valor propio. */
export function probabilidadesDeValores(valores: ValoresProbabilidades): Record<string, number> {
  const salida: Record<string, number> = {};
  for (const [etapa, texto] of Object.entries(valores.probabilidades_etapa)) {
    const numero = numeroDeTexto(texto);
    if (numero != null) salida[etapa] = numero;
  }
  return salida;
}

export function ProbabilidadesEtapaCard({
  organizationId,
  canManage,
}: {
  organizationId: number;
  canManage: boolean;
}) {
  const { data, isLoading, isError } = useOrganizationSettings(organizationId);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Percent className="h-4 w-4 text-primary" aria-hidden="true" />
          Probabilidad de cierre por etapa
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          Con estos porcentajes se pondera el valor del pipeline en Mi Pipeline → Embudo: cada
          oportunidad abierta cuenta su importe por la probabilidad de su etapa. Un campo vacío
          usa el valor por defecto.
        </p>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : isError || !data ? (
          <p role="alert" className="text-sm text-destructive">
            No se pudo cargar la configuración de la organización.
          </p>
        ) : (
          <FormularioProbabilidades
            key={JSON.stringify(data.probabilidades_etapa ?? {})}
            organizationId={organizationId}
            ajustes={data}
            canManage={canManage}
          />
        )}
      </CardContent>
    </Card>
  );
}

function FormularioProbabilidades({
  organizationId,
  ajustes,
  canManage,
}: {
  organizationId: number;
  ajustes: OrganizationSettingsOut;
  canManage: boolean;
}) {
  const defaults = ajustes.probabilidades_etapa_default ?? {};
  const etapas = ordenarEtapas(Object.keys(defaults));
  const guardar = useUpdateOrganizationSettings(organizationId);
  const formulario = useForm<ValoresProbabilidades>({
    resolver: zodResolver(probabilidadesEtapa.esquema),
    defaultValues: valoresDeAjustes(ajustes, etapas),
  });
  const errores = formulario.formState.errors.probabilidades_etapa;

  const onSubmit = formulario.handleSubmit(async (valores) => {
    try {
      await guardar.mutateAsync({ probabilidades_etapa: probabilidadesDeValores(valores) });
      toast.success("Probabilidades guardadas. El valor ponderado ya las usa.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "No se pudieron guardar");
    }
  });

  if (etapas.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        El servidor no ha enviado las etapas del pipeline.
      </p>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3" noValidate>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {etapas.map((etapa) => {
          const id = `probabilidad-${organizationId}-${etapa}`;
          const mensaje = errores?.[etapa]?.message;
          return (
            <div key={etapa} className="space-y-1">
              <label htmlFor={id} className="text-xs font-medium">
                {etiquetaEtapa(etapa)} (%)
              </label>
              <Input
                id={id}
                inputMode="numeric"
                disabled={!canManage}
                placeholder={`${defaults[etapa]} (por defecto)`}
                {...formulario.register(`probabilidades_etapa.${etapa}`)}
                {...ariaCampo(id, mensaje)}
              />
              <CampoError campoId={id} mensaje={mensaje} />
            </div>
          );
        })}
      </div>
      {canManage ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" size="sm" disabled={guardar.isPending}>
            {guardar.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Save className="h-4 w-4" aria-hidden="true" />
            )}
            Guardar probabilidades
          </Button>
          <span className="text-xs text-muted-foreground">
            Enteros de 0 a 100. Ganadas y perdidas no se ponderan: ya no son pipeline.
          </span>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">Solo owner o admin pueden cambiarlas.</p>
      )}
    </form>
  );
}
