"use client";

/**
 * Los pesos que sugieren las decisiones de la organización (S3.3).
 *
 * El backend compara el desglose sellado de lo ganado con el de lo perdido o,
 * mientras no haya bastantes cierres, el de lo que el equipo abre con el de lo
 * que descarta (`fuente`), y propone un reparto que sigue sumando 100. La
 * tarjeta rotula cada lado según la fuente. Tres reglas de producto, y las tres
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
 *
 * Aplicar reescribe el perfil guardado y el formulario de la página se
 * recarga con él. Con cambios sin guardar eso los tiraría sin avisar —unas
 * palabras clave recién añadidas, por ejemplo—, así que mientras los haya no
 * se puede aplicar (`bloqueada`).
 */

import { useState } from "react";
import { ArrowRight } from "lucide-react";
import { toast } from "sonner";
import { Panel, PanelError, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import {
  type PesoPropuestoDimension,
  type PesosPropuestos,
  useApplyWeightsProposal,
  useWeightsProposal,
} from "@/hooks/use-weights-proposal";
import { formatNumber } from "@/lib/utils";
import { WEIGHT_LABELS } from "../_lib/pesos";

const ORIGEN_LABEL: Record<PesosPropuestos["origen_pesos_actuales"], string> = {
  perfil: "tus pesos guardados",
  global: "los pesos globales (todavía no has guardado un perfil)",
};

/** Cómo se llaman los dos lados de la comparación en cada fuente. */
const LADOS: Record<PesosPropuestos["fuente"], { a: string; b: string }> = {
  cierres: { a: "ganadas", b: "perdidas" },
  triaje: { a: "abiertas", b: "descartadas" },
};

function plural(n: number, singular: string, varios: string) {
  return `${n} ${n === 1 ? singular : varios}`;
}

function Base({ propuesta }: { propuesta: PesosPropuestos }) {
  const base =
    propuesta.fuente === "triaje"
      ? `tu triaje: ${plural(propuesta.n_abiertas, "oportunidad abierta", "oportunidades abiertas")} y ${plural(propuesta.n_descartadas, "señal descartada", "señales descartadas")}, con desglose sellado (todavía hay pocos cierres)`
      : `${plural(propuesta.n_cierres, "cierre", "cierres")} con desglose sellado: ${plural(propuesta.n_ganadas, "ganada", "ganadas")} y ${plural(propuesta.n_perdidas, "perdida", "perdidas")}`;
  return (
    <p className="text-tf-meta text-muted-foreground">
      Base: {base}. Se compara contra {ORIGEN_LABEL[propuesta.origen_pesos_actuales]}.
    </p>
  );
}

function DimensionRow({
  dimension,
  fuente,
}: {
  dimension: PesoPropuestoDimension;
  fuente: PesosPropuestos["fuente"];
}) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-divider py-2 last:border-0">
      <div className="min-w-0">
        <p className="text-tf-body font-medium">{WEIGHT_LABELS[dimension.dimension] ?? dimension.dimension}</p>
        <p className="text-tf-meta text-muted-foreground">
          Media en {LADOS[fuente].a} {formatNumber(dimension.media_ganadas)} · en {LADOS[fuente].b}{" "}
          {formatNumber(dimension.media_perdidas)} (diferencia {formatNumber(dimension.delta)})
        </p>
      </div>
      {/* Un cambio (antes → después): la flecha es el único sitio donde la
          regla de la casa la admite, y el lector de pantalla lee «pasa a». */}
      <div className="tf-tnum flex flex-none items-center gap-2 text-tf-body">
        <span className="text-muted-foreground">{dimension.peso_actual}</span>
        <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
        <span className="sr-only"> pasa a </span>
        <span className="font-semibold">{dimension.peso_propuesto}</span>
      </div>
    </li>
  );
}

function Insuficiente({ propuesta }: { propuesta: PesosPropuestos }) {
  const minimo = propuesta.minimo_triaje_por_lado;
  return (
    <p className="text-tf-body text-muted-foreground">
      Todavía no hay base para proponer nada. Hacen falta{" "}
      <span className="font-medium text-foreground">{propuesta.minimo_cierres}</span> cierres con desglose
      sellado (llevas {propuesta.n_cierres}) o, mientras tanto,{" "}
      <span className="font-medium text-foreground">{minimo}</span> oportunidades abiertas y {minimo} señales
      descartadas desde el Radar o el resumen diario (llevas {propuesta.n_abiertas} y{" "}
      {propuesta.n_descartadas}). Un ajuste sobre menos decisiones diría más del azar que de tu equipo.
    </p>
  );
}

export function PesosPropuestosCard({ bloqueada = false }: { bloqueada?: boolean }) {
  const { data, isPending, error, refetch } = useWeightsProposal();
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
      // El aviso de error es el global de mutaciones (meta.errorTitle del hook, D6).
      .catch(() => undefined);
  };

  return (
    <Panel>
      <PanelTitle title="Pesos que sugieren tus decisiones" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Comparación entre el desglose del score de lo que tu organización ganó y el de lo que perdió o, mientras
        haya pocos cierres, de lo que abrió y lo que descartó. Es una propuesta: no se aplica sola.
      </p>
      <div className="space-y-3">
        {isPending && <p className="text-tf-meta text-muted-foreground">Calculando la propuesta…</p>}

        {!isPending && (error || !data) && (
          <PanelError
            variant="inline"
            title="No se pudo calcular la propuesta de pesos"
            error={error ?? undefined}
            onRetry={() => void refetch()}
          />
        )}

        {data && data.estado === "insuficiente" && <Insuficiente propuesta={data} />}

        {data && data.estado === "propuesta" && (
          <>
            <Base propuesta={data} />
            {hayPropuesta ? (
              <ul className="mt-1">
                {dimensiones.map((dimension) => (
                  <DimensionRow key={dimension.dimension} dimension={dimension} fuente={data.fuente} />
                ))}
              </ul>
            ) : (
              <p className="text-tf-body text-muted-foreground">
                No sale ningún ajuste: las dimensiones puntuaron igual en lo{" "}
                {data.fuente === "triaje" ? "abierto y en lo descartado" : "ganado y en lo perdido"}.
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
              disabled={aplicar.isPending || bloqueada}
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
            <span className="text-tf-meta text-muted-foreground">
              {bloqueada
                ? "Guarda o descarta antes tus cambios: aplicar la propuesta recarga el perfil y los perdería."
                : "Sustituye los pesos de tu perfil y queda registrado."}
            </span>
          </div>
        )}
      </div>
    </Panel>
  );
}
