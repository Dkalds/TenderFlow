"use client";

/**
 * Cierre asistido: el sistema ya sabe que este expediente se adjudicó.
 *
 * Hasta 2026-09 ganada, perdida e importe adjudicado se tecleaban a mano
 * aunque la ingesta trajera adjudicatario, importe y número de ofertas del
 * mismo expediente: el win rate dependía de que alguien se acordara de volver
 * a la ficha, y sin outcomes fiables la fase de precio calibrado no puede
 * empezar.
 *
 * Lo que este componente **no** hace es decidir quién ganó. Desde S2.1 el
 * backend sí propone un resultado (`resultado_sugerido`, cruzando los NIFs que
 * la organización declaró con los de los adjudicatarios publicados), y la ficha
 * lo trae **preseleccionado**: el atajo se lo lleva el caso normal, que es que
 * la propuesta acierte. Pero preseleccionar no es cerrar — la opción se puede
 * cambiar y el cierre exige una confirmación explícita—, porque el resultado
 * es justo el dato que las métricas de producto existen para medir y un cierre
 * automático equivocado lo contamina sin que nadie se entere.
 *
 * Con `resultado_sugerido: null` —la organización no ha declarado NIFs, o la
 * fuente no publicó el del adjudicatario— la tarjeta se comporta como antes de
 * S2.1: dos botones y ninguna preselección. `null` es «no lo sé», no «no ganó».
 */
import { useState } from "react";
import { CircleCheck, Trophy } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useUpdatePursuit, type Pursuit } from "@/hooks/use-pursuits";
import { EMPTY, formatCurrency } from "@/lib/utils";
import { formatDate } from "@/components/pursuits/pursuit-presenters";

type Resultado = "won" | "lost";

function nombresDe(adjudicatarios: { nombre: string }[]): string {
  return adjudicatarios.map((a) => a.nombre).join(", ");
}

const ETIQUETA: Record<Resultado, string> = { won: "La ganamos", lost: "La perdimos" };

export function AdjudicacionDetectada({ pursuit }: { pursuit: Pursuit }) {
  const adjudicacion = pursuit.adjudicacion;
  const update = useUpdatePursuit(pursuit.id);
  const sugerido = adjudicacion?.resultado_sugerido ?? null;
  // Sólo se guarda lo que la persona ha cambiado; la preselección sale de la
  // propuesta en cada render. Va atada al `id` porque la ruta reutiliza el
  // componente al saltar de una oportunidad a otra, y arrastrar la elección
  // anterior preseleccionaría un resultado que nadie ha propuesto aquí.
  const [eleccion, setEleccion] = useState<{ id: number; valor: Resultado } | null>(null);

  // Sin adjudicación publicada no hay nada que proponer. Es el caso normal de
  // una oportunidad viva, no un estado de error.
  if (!adjudicacion) return null;

  const adjudicatarios = adjudicacion.adjudicatarios ?? [];
  const puedeCerrar = adjudicacion.cierre_pendiente && pursuit.status === "submitted";
  const motivo = `Adjudicación publicada por la fuente: ${nombresDe(adjudicatarios) || "sin adjudicatario publicado"}`;
  const seleccion: Resultado =
    (eleccion?.id === pursuit.id ? eleccion.valor : null) ?? sugerido ?? "lost";

  const cerrar = async (outcome: Resultado) => {
    try {
      await update.mutateAsync({
        outcome,
        // El importe adjudicado es el del contrato, así que sólo acompaña a
        // «ganada»: en una perdida ese número es del competidor.
        ...(outcome === "won" ? { awarded_amount_eur: adjudicacion.importe_total ?? null } : {}),
        outcome_reason: motivo,
        expected_version: pursuit.version,
      });
      toast.success(outcome === "won" ? "Oportunidad cerrada como ganada" : "Oportunidad cerrada como perdida");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "No se pudo cerrar la oportunidad");
    }
  };

  const retirar = async () => {
    try {
      await update.mutateAsync({ status: "withdrawn", expected_version: pursuit.version });
      toast.success("Oportunidad retirada");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "No se pudo retirar la oportunidad");
    }
  };

  return (
    <section
      className="mb-4 rounded-xl border border-primary/30 bg-primary/[0.06] px-4 py-3.5"
      aria-labelledby="adjudicacion-detectada-titulo"
    >
      <div className="mb-2.5 flex items-center gap-2">
        <Trophy className="h-4 w-4 flex-none text-primary" aria-hidden="true" />
        <h3 id="adjudicacion-detectada-titulo" className="text-[13px] font-semibold">
          Este expediente ya se adjudicó
        </h3>
      </div>

      <ul className="mb-3 space-y-1.5">
        {adjudicatarios.map((a, indice) => (
          <li key={`${a.nif ?? a.nombre}-${indice}`} className="text-[12.5px] leading-[1.45]">
            <span className="font-medium">{a.nombre}</span>
            <span className="text-muted-foreground">
              {" · "}
              {a.importe_adjudicado != null ? formatCurrency(a.importe_adjudicado) : EMPTY}
              {a.n_ofertas_recibidas != null && ` · ${a.n_ofertas_recibidas} ofertas`}
              {a.fecha_adjudicacion && ` · ${formatDate(a.fecha_adjudicacion)}`}
            </span>
          </li>
        ))}
      </ul>

      {adjudicacion.importe_total != null && adjudicatarios.length > 1 && (
        <p className="mb-3 text-[12px]">
          Importe total adjudicado:{" "}
          <span className="font-semibold">{formatCurrency(adjudicacion.importe_total)}</span>
        </p>
      )}

      {puedeCerrar && sugerido ? (
        <div className="space-y-2.5">
          <fieldset className="border-0 p-0">
            <legend className="mb-1.5 text-[11.5px] leading-[1.5] text-muted-foreground">
              Por el NIF de tu organización, esto parece una oportunidad{" "}
              <span className="font-medium text-foreground">
                {sugerido === "won" ? "ganada" : "perdida"}
              </span>
              . Cámbialo si no es así: el cierre lo confirmas tú.
            </legend>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
              {(["won", "lost"] as const).map((opcion) => (
                <label key={opcion} className="flex items-center gap-1.5 text-[12.5px]">
                  <input
                    type="radio"
                    name={`adjudicacion-resultado-${pursuit.id}`}
                    value={opcion}
                    checked={seleccion === opcion}
                    onChange={() => setEleccion({ id: pursuit.id, valor: opcion })}
                    disabled={update.isPending}
                    className="h-3.5 w-3.5 accent-primary"
                  />
                  {ETIQUETA[opcion]}
                </label>
              ))}
            </div>
          </fieldset>
          <Button size="sm" disabled={update.isPending} onClick={() => void cerrar(seleccion)}>
            <CircleCheck aria-hidden="true" />
            {seleccion === "won" ? "Confirmar como ganada" : "Confirmar como perdida"}
          </Button>
        </div>
      ) : puedeCerrar ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={update.isPending} onClick={() => void cerrar("won")}>
            <CircleCheck aria-hidden="true" />
            Cerrar como ganada
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={update.isPending}
            onClick={() => void cerrar("lost")}
          >
            Cerrar como perdida
          </Button>
          <span className="text-[11px] text-muted-foreground">
            El resultado lo decides tú: el sistema no sabe cuál de estas empresas sois.
          </span>
        </div>
      ) : adjudicacion.cierre_pendiente ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[11.5px] leading-[1.5] text-muted-foreground">
            Para cerrar con resultado hay que registrar antes la oferta presentada (estado «Oferta
            presentada»), o retirar la oportunidad.
          </p>
          <Button
            size="sm"
            variant="outline"
            disabled={update.isPending}
            onClick={() => void retirar()}
          >
            Marcar como retirada
          </Button>
        </div>
      ) : (
        <p className="text-[11.5px] leading-[1.5] text-muted-foreground">
          Esta oportunidad ya está cerrada. La adjudicación se muestra como contexto.
        </p>
      )}
    </section>
  );
}
