"use client";

/**
 * Los pesos que sugieren los cierres de la organización (S3.3).
 *
 * El backend compara el desglose sellado de lo ganado con el de lo perdido y
 * propone un reparto que sigue sumando 100. Tres reglas de producto, y las tres
 * son del plan:
 *
 * 1. **La propuesta viaja con su base.** Cuántos cierres, cuántas ganadas y
 *    cuántas perdidas la sostienen. Un ajuste sin universo no se puede juzgar.
 * 2. **Por debajo del mínimo no hay propuesta, y la tarjeta no se esconde.** Se
 *    dice cuántos cierres faltan: es lo que convierte «no hay dato» en algo
 *    accionable.
 * 3. **Aplicar es un clic explícito y confirmado.** Nunca se aplica sola, y el
 *    POST no lleva pesos: el backend recalcula y escribe lo mismo que se
 *    enseñó, y deja rastro en `audit_log`.
 */

import { useState } from "react";
import { ArrowRight, Scale } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  type PesoPropuestoDimension,
  type PesosPropuestos,
  useApplyWeightsProposal,
  useWeightsProposal,
} from "@/hooks/use-weights-proposal";
import { formatNumber } from "@/lib/utils";
import { WEIGHT_LABELS } from "./pesos-scoring-card";

const ORIGEN_LABEL: Record<PesosPropuestos["origen_pesos_actuales"], string> = {
  perfil: "tus pesos guardados",
  global: "los pesos globales (todavía no has guardado un perfil)",
};

function Base({ propuesta }: { propuesta: PesosPropuestos }) {
  return (
    <p className="text-xs text-muted-foreground">
      Base: {propuesta.n_cierres} cierre{propuesta.n_cierres === 1 ? "" : "s"} con desglose sellado
      — {propuesta.n_ganadas} ganada{propuesta.n_ganadas === 1 ? "" : "s"} y{" "}
      {propuesta.n_perdidas} perdida{propuesta.n_perdidas === 1 ? "" : "s"}. Se compara contra{" "}
      {ORIGEN_LABEL[propuesta.origen_pesos_actuales]}.
    </p>
  );
}

function DimensionRow({ dimension }: { dimension: PesoPropuestoDimension }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border/50 py-2 last:border-0">
      <div className="min-w-0">
        <p className="text-sm font-medium">
          {WEIGHT_LABELS[dimension.dimension] ?? dimension.dimension}
        </p>
        <p className="text-xs text-muted-foreground">
          Media en ganadas {formatNumber(dimension.media_ganadas)} · en perdidas{" "}
          {formatNumber(dimension.media_perdidas)} (diferencia {formatNumber(dimension.delta)})
        </p>
      </div>
      <div className="flex flex-none items-center gap-2 text-sm tabular-nums">
        <span className="text-muted-foreground">{dimension.peso_actual}</span>
        <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
        <span className="font-semibold">{dimension.peso_propuesto}</span>
      </div>
    </li>
  );
}

function Insuficiente({ propuesta }: { propuesta: PesosPropuestos }) {
  const faltan = propuesta.minimo_cierres - propuesta.n_cierres;
  return (
    <p className="text-sm text-muted-foreground">
      Todavía no hay base para proponer nada: llevas{" "}
      <span className="font-medium text-foreground">{propuesta.n_cierres}</span> de{" "}
      {propuesta.minimo_cierres} cierres con desglose sellado, así que faltan{" "}
      <span className="font-medium text-foreground">{faltan}</span>. Un ajuste sobre menos
      cierres diría más del azar que de lo que gana tu equipo.
    </p>
  );
}

export function PesosPropuestosCard() {
  const { data, isLoading, error } = useWeightsProposal();
  const aplicar = useApplyWeightsProposal();
  const [confirmando, setConfirmando] = useState(false);

  const dimensiones = data?.dimensiones ?? [];
  const hayPropuesta = data?.estado === "propuesta" && dimensiones.length > 0;

  const onAplicar = () => {
    if (!confirmando) {
      setConfirmando(true);
      return;
    }
    aplicar
      .mutateAsync()
      .then(() => {
        setConfirmando(false);
        toast.success("Pesos aplicados a tu perfil. El Radar ya puntúa con ellos.");
      })
      .catch((err: unknown) =>
        toast.error(err instanceof Error ? err.message : "No se pudieron aplicar los pesos"),
      );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Scale className="h-4 w-4 text-primary" aria-hidden="true" />
          Pesos que sugieren tus cierres
        </CardTitle>
        <CardDescription>
          Comparación entre el desglose de score de lo que tu organización ganó y el de lo que
          perdió. Es una propuesta: no se aplica sola.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading && <p className="text-sm text-muted-foreground">Calculando la propuesta…</p>}

        {!isLoading && (error || !data) && (
          <p className="text-sm text-muted-foreground">
            No se pudo calcular la propuesta de pesos.
          </p>
        )}

        {data && data.estado === "insuficiente" && <Insuficiente propuesta={data} />}

        {data && data.estado === "propuesta" && (
          <>
            <Base propuesta={data} />
            {hayPropuesta ? (
              <ul className="mt-1">
                {dimensiones.map((dimension) => (
                  <DimensionRow key={dimension.dimension} dimension={dimension} />
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">
                Con esos cierres no sale ningún ajuste: las dimensiones puntuaron igual en lo
                ganado y en lo perdido.
              </p>
            )}
          </>
        )}

        {hayPropuesta && (
          <div className="flex flex-wrap items-center gap-3 pt-1">
            <Button
              size="sm"
              variant={confirmando ? "default" : "outline"}
              onClick={onAplicar}
              disabled={aplicar.isPending}
            >
              {aplicar.isPending
                ? "Aplicando…"
                : confirmando
                  ? "¿Aplicar estos pesos a tu perfil?"
                  : "Aplicar la propuesta"}
            </Button>
            {confirmando && !aplicar.isPending && (
              <Button variant="ghost" size="sm" onClick={() => setConfirmando(false)}>
                Cancelar
              </Button>
            )}
            <span className="text-xs text-muted-foreground">
              Sustituye los pesos de tu perfil y queda registrado.
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
