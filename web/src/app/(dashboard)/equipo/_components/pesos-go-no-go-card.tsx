"use client";

/**
 * Pesos de la matriz go/no-go, en Equipo → Organización (C6.4, D30).
 *
 * Cada oportunidad se puntúa de 1 a 5 en cinco criterios y la API recomienda
 * ir cuando la media ponderada llega al umbral; con esa recomendación marca
 * también las decisiones que la contradicen. Los pesos son de la organización
 * —decide quien responde de cómo decide el equipo— y hasta ahora solo se
 * podían cambiar por la API.
 *
 * Calcado de `probabilidades-etapa-card.tsx`, con estas diferencias:
 * - **Los pesos son relativos**, no porcentajes: 2 y 1 es «el doble». Al lado
 *   de cada campo va qué parte del total supone con lo que hay escrito, para
 *   que «3» no se lea como «3 %».
 * - **Todos a cero no se guarda**: el backend lo trataría en silencio como
 *   «sin configurar» y volvería a los pesos iguales
 *   (`services/go_no_go_template.py::normalizar_pesos`).
 * - **Los criterios, sus etiquetas y el umbral** vienen en la respuesta.
 * - El permiso lo decide el backend (403 si no eres propietario ni
 *   administrador); la pantalla solo evita ofrecer lo que va a fallar.
 */

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod/mini";

import { Panel, PanelError, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { esquemaDeDto } from "@/lib/forms/dto-schema";
import { numeroDeTexto } from "@/lib/forms/valores";
import { getErrorMessage } from "@/lib/query-feedback";
import { formatNumber, formatPercent } from "@/lib/utils";

import { type PesosGoNoGo, useGuardarPesosGoNoGo, usePesosGoNoGo } from "../_hooks/use-pesos-go-no-go";

/** Techo del formulario: el backend no pone uno, pero 1.000 frente a 1 es una errata. */
const PESO_MAXIMO = 100;

const pesoTexto = z.string().check(
  z.refine((valor) => {
    const numero = numeroDeTexto(valor);
    return numero != null && numero >= 0 && numero <= PESO_MAXIMO;
  }, `Escribe un peso entre 0 y ${PESO_MAXIMO}.`),
);

/** `api/routes/pursuits.py::GoNoGoWeightsIn`: un peso por criterio. */
const pesosGoNoGo = esquemaDeDto("GoNoGoWeightsIn")({ pesos: z.record(z.string(), pesoTexto) }, []);

const TODOS_A_CERO = "Al menos un criterio tiene que pesar algo: con todos a cero la matriz no puede recomendar.";

/**
 * ¿Algún peso es mayor que cero? Es una regla del conjunto, no de un campo, y
 * por eso se comprueba al enviar y se pinta como error del formulario: en el
 * esquema acabaría colgada de `errors.pesos`, que es el registro de campos.
 */
export function algunPesoPositivo(pesos: Record<string, string>): boolean {
  return Object.values(pesos).some((texto) => (numeroDeTexto(texto) ?? 0) > 0);
}

interface ValoresPesos {
  pesos: Record<string, string>;
}

function valoresDePesos(datos: PesosGoNoGo): ValoresPesos {
  return {
    pesos: Object.fromEntries(datos.criterios.map((c) => [c.criterio, c.peso != null ? String(c.peso) : ""])),
  };
}

/** Del formulario al contrato: todos los criterios, como número. */
export function pesosDeValores(valores: ValoresPesos): Record<string, number> {
  const salida: Record<string, number> = {};
  for (const [criterio, texto] of Object.entries(valores.pesos)) {
    const numero = numeroDeTexto(texto);
    if (numero != null) salida[criterio] = numero;
  }
  return salida;
}

/** Qué parte del total supone cada peso, o `null` si no se puede decir aún. */
export function partesDelTotal(pesos: Record<string, string>): Record<string, number | null> {
  const numeros = Object.fromEntries(Object.entries(pesos).map(([c, texto]) => [c, numeroDeTexto(texto)]));
  const validos = Object.values(numeros).filter((n): n is number => n != null && n >= 0);
  const total = validos.reduce((suma, n) => suma + n, 0);
  return Object.fromEntries(
    Object.entries(numeros).map(([c, n]) => [c, n != null && n >= 0 && total > 0 ? (n / total) * 100 : null]),
  );
}

export function PesosGoNoGoCard({ organizationId, canManage }: { organizationId: number; canManage: boolean }) {
  const { data, isLoading, error, refetch } = usePesosGoNoGo(organizationId);

  return (
    <Panel>
      <PanelTitle title="Pesos de la matriz go/no-go" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Cada oportunidad se puntúa de 1 a 5 en estos criterios, y la recomendación es ir cuando la media ponderada
        llega al umbral. Con ella se marcan también las decisiones que la contradicen. Los pesos son relativos: un 2
        cuenta el doble que un 1.
      </p>
      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : error || !data ? (
        <PanelError
          variant="inline"
          title="No se pudieron cargar los pesos del go/no-go"
          error={error ?? undefined}
          onRetry={() => void refetch()}
        />
      ) : (
        <FormularioPesos
          key={JSON.stringify(data.criterios.map((c) => [c.criterio, c.peso]))}
          organizationId={organizationId}
          datos={data}
          canManage={canManage}
        />
      )}
    </Panel>
  );
}

function FormularioPesos({
  organizationId,
  datos,
  canManage,
}: {
  organizationId: number;
  datos: PesosGoNoGo;
  canManage: boolean;
}) {
  const guardar = useGuardarPesosGoNoGo(organizationId);
  const formulario = useForm<ValoresPesos>({
    resolver: zodResolver(pesosGoNoGo.esquema),
    defaultValues: valoresDePesos(datos),
  });
  const escritos = useWatch({ control: formulario.control, name: "pesos" });
  const partes = partesDelTotal(escritos ?? {});
  const errores = formulario.formState.errors.pesos;
  const errorConjunto = formulario.formState.errors.root?.message;

  const onSubmit = formulario.handleSubmit(async (valores) => {
    if (!algunPesoPositivo(valores.pesos)) {
      formulario.setError("root", { message: TODOS_A_CERO });
      return;
    }
    try {
      await guardar.mutateAsync(pesosDeValores(valores));
      toast.success("Pesos guardados. La recomendación de cada oportunidad ya los usa.");
    } catch (fallo) {
      toast.error(getErrorMessage(fallo, "accion"));
    }
  });

  if (datos.criterios.length === 0) {
    return <p className="text-tf-meta text-muted-foreground">No hay criterios que ponderar.</p>;
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3" noValidate>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {datos.criterios.map((criterio) => {
          const id = `peso-go-no-go-${organizationId}-${criterio.criterio}`;
          const parte = partes[criterio.criterio];
          return (
            <Field
              key={criterio.criterio}
              label={criterio.etiqueta}
              htmlFor={id}
              error={errores?.[criterio.criterio]?.message}
              hint={parte != null ? `${formatPercent(parte, 0)} del total` : undefined}
            >
              <Input
                id={id}
                inputMode="decimal"
                disabled={!canManage}
                {...formulario.register(`pesos.${criterio.criterio}`)}
              />
            </Field>
          );
        })}
      </div>
      {errorConjunto && (
        <p role="alert" className="text-tf-meta text-destructive">
          {errorConjunto}
        </p>
      )}
      <p className="text-tf-meta text-muted-foreground">
        Recomienda ir con una media ponderada de {formatNumber(datos.umbral, "es-ES", { decimales: 1 })} o más, en la
        escala de 1 a 5.
      </p>
      {canManage ? (
        <Button type="submit" size="sm" disabled={guardar.isPending}>
          {guardar.isPending ? "Guardando…" : "Guardar pesos"}
        </Button>
      ) : (
        <p className="text-tf-meta text-muted-foreground">Solo un propietario o un administrador puede cambiarlos.</p>
      )}
    </form>
  );
}
