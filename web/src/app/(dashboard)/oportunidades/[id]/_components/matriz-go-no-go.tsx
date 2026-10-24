"use client";

import * as React from "react";
import { toast } from "sonner";
import {
  Aviso,
  EnlaceIr,
  Panel,
  PanelError,
  PanelLoading,
  SectionTitle,
  Segmented,
  type OpcionSegmented,
} from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { decisionLabel } from "@/components/pursuits/pursuit-presenters";
import { usePuedeEscribir } from "@/hooks/use-organization";
import {
  usePuntuarCriterio,
  usePursuitGoNoGo,
  type CriterioPuntuado,
} from "@/hooks/use-pursuit-go-no-go";
import type { Pursuit } from "@/hooks/use-pursuits";
import { getErrorMessage } from "@/lib/query-feedback";
import { cn, EMPTY, formatNumber } from "@/lib/utils";

/**
 * Matriz go/no-go de la ficha: cinco criterios puntuados de 1 a 5, cada uno
 * con su motivo, y lo que la plantilla recomienda con ellos (C6.4, D30).
 *
 * **Informa, no decide.** La decisión sigue siendo la del comité, justo
 * encima. Lo que sí hace la matriz es dejar visible cuándo esa decisión
 * contradice lo que recomienda (`discrepa`): no para impedirla —el equipo sabe
 * cosas que la plantilla no—, sino para que quede a la vista y se pueda
 * revisar después.
 *
 * Nada se calcula aquí (ADR-014): el total ponderado, el umbral, la
 * recomendación, cuántos criterios entraron y si la decisión discrepa llegan
 * del servidor, que pondera con los pesos de la organización. Los criterios y
 * sus etiquetas también salen de la respuesta.
 *
 * Una matriz a medias es **provisional**: el backend promedia solo lo
 * puntuado, y por eso el recuento («sobre 3 de 5 criterios») va siempre junto
 * al total.
 */

const ESCALA: readonly OpcionSegmented<string>[] = ["1", "2", "3", "4", "5"].map((valor) => ({
  value: valor,
  label: valor,
}));

/** Lo que el usuario ha cambiado de un criterio y aún no ha guardado. */
interface Borrador {
  puntuacion?: number;
  motivo?: string;
}

const RECOMENDACION: Record<string, { texto: string; clase: string; sentido?: string }> = {
  go: { texto: "Recomienda GO", clase: "text-success", sentido: "GO" },
  no_go: { texto: "Recomienda NO-GO", clase: "text-destructive", sentido: "NO-GO" },
  sin_datos: { texto: "Sin criterios puntuados", clase: "text-muted-foreground" },
};

/** El `decision` del servidor es `string`: solo se rotula lo que se conoce. */
function decisionTomada(decision: string | null | undefined): string | null {
  if (decision === "go" || decision === "no_go") return decisionLabel(decision);
  return null;
}

function FilaCriterio({
  criterio,
  borrador,
  editable,
  guardando,
  onCambio,
  onGuardar,
}: {
  criterio: CriterioPuntuado;
  borrador: Borrador | undefined;
  editable: boolean;
  guardando: boolean;
  onCambio: (cambio: Borrador) => void;
  onGuardar: (puntuacion: number, motivo: string) => void;
}) {
  const puntuacion = borrador?.puntuacion ?? criterio.puntuacion ?? null;
  const motivo = borrador?.motivo ?? criterio.motivo ?? "";
  const sucio =
    puntuacion !== (criterio.puntuacion ?? null) || motivo.trim() !== (criterio.motivo ?? "").trim();

  return (
    <li className="border-border/60 border-t py-2.5 first:border-t-0 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
        <p className="text-tf-body font-medium">{criterio.etiqueta}</p>
        {editable ? (
          <Segmented
            aria-label={`Puntuación de «${criterio.etiqueta}»`}
            size="xs"
            value={puntuacion == null ? "" : String(puntuacion)}
            onChange={(valor) => onCambio({ puntuacion: Number(valor) })}
            options={ESCALA}
          />
        ) : (
          <p className="tf-tnum text-tf-body font-semibold">
            {criterio.puntuacion == null ? "Sin puntuar" : `${criterio.puntuacion} de 5`}
          </p>
        )}
      </div>

      {editable ? (
        <div className="mt-1.5 flex items-center gap-2">
          <Input
            aria-label={`Motivo de «${criterio.etiqueta}»`}
            value={motivo}
            maxLength={1000}
            placeholder="Por qué esta puntuación"
            onChange={(event) => onCambio({ motivo: event.target.value })}
            className="h-8 flex-1 text-tf-body"
          />
          {sucio ? (
            <Button
              size="sm"
              disabled={puntuacion == null || guardando}
              onClick={() => puntuacion != null && onGuardar(puntuacion, motivo.trim())}
              aria-label={`Guardar «${criterio.etiqueta}»`}
            >
              {guardando ? "Guardando…" : "Guardar"}
            </Button>
          ) : null}
        </div>
      ) : criterio.motivo ? (
        <p className="text-muted-foreground mt-1 text-tf-meta">{criterio.motivo}</p>
      ) : null}

      {criterio.puntuacion != null && criterio.author_name ? (
        <p className="text-muted-foreground mt-1 text-tf-micro">Puntuó {criterio.author_name}</p>
      ) : null}
    </li>
  );
}

export function MatrizGoNoGo({ pursuit }: { pursuit: Pursuit }) {
  const { data, isPending, error, refetch } = usePursuitGoNoGo(pursuit.id);
  const puntuar = usePuntuarCriterio(pursuit.id);
  const puedeEscribir = usePuedeEscribir();
  const [borradores, setBorradores] = React.useState<Record<string, Borrador>>({});
  const [guardandoCriterio, setGuardandoCriterio] = React.useState<string | null>(null);

  if (isPending) {
    return (
      <Panel id="ficha-matriz" role="region" aria-label="Matriz go/no-go">
        <SectionTitle>Matriz go/no-go</SectionTitle>
        <PanelLoading height={220} />
      </Panel>
    );
  }

  if (error || !data) {
    return (
      <Panel id="ficha-matriz" role="region" aria-label="Matriz go/no-go">
        <SectionTitle>Matriz go/no-go</SectionTitle>
        <PanelError
          variant="inline"
          title="No se pudo cargar la matriz go/no-go"
          error={error}
          message={error ? undefined : "No hay respuesta que enseñar. Vuelve a intentarlo."}
          onRetry={() => void refetch()}
        />
      </Panel>
    );
  }

  const totalCriterios = data.criterios.length;
  const recomendacion = RECOMENDACION[data.recomendacion] ?? RECOMENDACION.sin_datos;
  const hayDatos = data.recomendacion !== "sin_datos";
  const tomada = decisionTomada(data.decision);

  const guardar = (criterio: string, puntuacion: number, motivo: string) => {
    setGuardandoCriterio(criterio);
    puntuar.mutate(
      { criterio, puntuacion, motivo: motivo || null },
      {
        onSuccess: () => {
          setBorradores((actuales) => {
            const resto = { ...actuales };
            delete resto[criterio];
            return resto;
          });
          toast.success("Puntuación guardada");
        },
        onError: (fallo) =>
          toast.error("No se pudo guardar la puntuación", {
            description: getErrorMessage(fallo, "accion"),
          }),
        onSettled: () => setGuardandoCriterio(null),
      },
    );
  };

  return (
    <Panel id="ficha-matriz" role="region" aria-label="Matriz go/no-go">
      <SectionTitle hint={`${data.criterios_puntuados} de ${totalCriterios} puntuados`}>
        Matriz go/no-go
      </SectionTitle>

      <div className="mb-3 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <p className="tf-tnum text-tf-title font-semibold" aria-label="Puntuación total">
          {hayDatos ? formatNumber(data.total, "es-ES", { decimales: 2 }) : EMPTY}
          <span className="text-muted-foreground text-tf-meta font-normal"> / 5</span>
        </p>
        <p className={cn("text-tf-body font-semibold", recomendacion.clase)}>{recomendacion.texto}</p>
        <p className="text-muted-foreground text-tf-meta">
          Umbral para el GO: {formatNumber(data.umbral, "es-ES", { decimales: 1 })}
        </p>
      </div>
      <p className="text-muted-foreground -mt-1.5 mb-3 text-tf-meta leading-relaxed">
        {!hayDatos
          ? "Puntúa al menos un criterio para obtener una recomendación."
          : data.completa
            ? `Calculada sobre los ${totalCriterios} criterios.`
            : `Provisional: calculada solo sobre ${data.criterios_puntuados} de ${totalCriterios} criterios. Los que faltan no cuentan.`}
      </p>

      {data.discrepa && tomada ? (
        <Aviso tone="warning" title={`La decisión ${tomada} contradice la matriz`} className="mb-3">
          La matriz recomienda {recomendacion.sentido}. La decisión puede estar justificada: queda
          a la vista para revisarla después.
        </Aviso>
      ) : null}

      <ul aria-label="Criterios">
        {data.criterios.map((criterio) => (
          <FilaCriterio
            key={criterio.criterio}
            criterio={criterio}
            borrador={borradores[criterio.criterio]}
            editable={puedeEscribir}
            guardando={guardandoCriterio === criterio.criterio}
            onCambio={(cambio) =>
              setBorradores((actuales) => ({
                ...actuales,
                [criterio.criterio]: { ...actuales[criterio.criterio], ...cambio },
              }))
            }
            onGuardar={(puntuacion, motivo) => guardar(criterio.criterio, puntuacion, motivo)}
          />
        ))}
      </ul>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <p className="text-muted-foreground text-tf-micro leading-relaxed">
          Orienta la decisión, no la toma: el GO o el NO-GO se marca a mano en «Decisión del comité».
        </p>
        <EnlaceIr href="/equipo?tab=organizacion">Pesos de los criterios</EnlaceIr>
      </div>
    </Panel>
  );
}
