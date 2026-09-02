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
 * Lo que este componente **no** hace es decidir quién ganó. El sistema no
 * conoce el NIF de la organización que usa la herramienta, así que deducir
 * «ganada» de que exista una adjudicación sería fabricar justo el dato que las
 * métricas de producto existen para medir. Propone, con los datos publicados a
 * la vista, y la persona confirma.
 */
import { CircleCheck, Trophy } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useUpdatePursuit, type Pursuit } from "@/hooks/use-pursuits";
import { EMPTY, formatCurrency } from "@/lib/utils";
import { formatDate } from "@/components/pursuits/pursuit-presenters";

function nombresDe(adjudicatarios: { nombre: string }[]): string {
  return adjudicatarios.map((a) => a.nombre).join(", ");
}

export function AdjudicacionDetectada({ pursuit }: { pursuit: Pursuit }) {
  const adjudicacion = pursuit.adjudicacion;
  const update = useUpdatePursuit(pursuit.id);

  // Sin adjudicación publicada no hay nada que proponer. Es el caso normal de
  // una oportunidad viva, no un estado de error.
  if (!adjudicacion) return null;

  const adjudicatarios = adjudicacion.adjudicatarios ?? [];
  const puedeCerrar = adjudicacion.cierre_pendiente && pursuit.status === "submitted";
  const motivo = `Adjudicación publicada por la fuente: ${nombresDe(adjudicatarios) || "sin adjudicatario publicado"}`;

  const cerrar = async (outcome: "won" | "lost") => {
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

      {puedeCerrar ? (
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
