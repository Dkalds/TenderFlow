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
 * Lo que este componente **no** hace es decidir quién ganó. Desde S2.1 la
 * API sí propone un resultado (`resultado_sugerido`, cruzando los NIFs que
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
 *
 * Cerrar como perdida pide el motivo de la lista cerrada de D37: la API
 * responde 422 a una pérdida sin `outcome_reason_code`. Si el acta de la mesa
 * trae puntuaciones y la fila propia, el motivo llega preseleccionado con lo
 * que proponen los puntos perdidos (spec §6.4) y se puede cambiar; sin
 * propuesta, el selector arranca vacío y el cierre espera a que alguien elija.
 */
import { useId, useState } from "react";
import { toast } from "sonner";
import { SUPERFICIE_PANEL, TONO_PANEL } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { AYUDA_CAMPO, ETIQUETA_CAMPO } from "@/components/ui/field";
import { useUpdatePursuit, type Pursuit } from "@/hooks/use-pursuits";
import { MOTIVOS_PERDIDA, type MotivoPerdida } from "@/lib/motivos-perdida";
import { cn, EMPTY, formatCurrency } from "@/lib/utils";
import { formatDate } from "@/components/pursuits/pursuit-presenters";
import {
  motivoSugeridoDe,
  PuntuacionesActa,
  type FilaActaRef,
} from "@/components/pursuits/puntuaciones-acta";

type Resultado = "won" | "lost";

function nombresDe(adjudicatarios: { nombre: string }[]): string {
  return adjudicatarios.map((a) => a.nombre).join(", ");
}

const ETIQUETA: Record<Resultado, string> = { won: "La ganamos", lost: "La perdimos" };

/**
 * Sin «Otro»: D37 lo exige con una nota que explique el motivo, y esta tarjeta
 * no tiene dónde escribirla (la nota de cierre es la adjudicación publicada).
 * Para «Otro» está el editor de la oportunidad, que sí la pide.
 */
const MOTIVOS = MOTIVOS_PERDIDA.filter((motivo) => motivo.codigo !== "otro");

export function AdjudicacionDetectada({ pursuit }: { pursuit: Pursuit }) {
  const adjudicacion = pursuit.adjudicacion;
  const update = useUpdatePursuit(pursuit.id, { errorTitle: "No se pudo cerrar la oportunidad" });
  const confirmacion = useUpdatePursuit(pursuit.id, {
    errorTitle: "No se pudo confirmar tu empresa en el acta",
  });
  const motivoId = useId();
  const sugerido = adjudicacion?.resultado_sugerido ?? null;
  // Sólo se guarda lo que la persona ha cambiado; la preselección sale de la
  // propuesta en cada render. Va atada al `id` porque la ruta reutiliza el
  // componente al saltar de una oportunidad a otra, y arrastrar la elección
  // anterior preseleccionaría un resultado que nadie ha propuesto aquí. Lo
  // mismo vale para el motivo y para el selector abierto.
  const [eleccion, setEleccion] = useState<{ id: number; valor: Resultado } | null>(null);
  const [motivoElegido, setMotivoElegido] = useState<{ id: number; valor: MotivoPerdida | "" } | null>(
    null,
  );
  const [perdidaAbierta, setPerdidaAbierta] = useState<number | null>(null);

  // Sin adjudicación publicada no hay nada que proponer. Es el caso normal de
  // una oportunidad viva, no un estado de error.
  if (!adjudicacion) return null;

  const adjudicatarios = adjudicacion.adjudicatarios ?? [];
  const puedeCerrar = adjudicacion.cierre_pendiente && pursuit.status === "submitted";
  const motivo = `Adjudicación publicada por la fuente: ${nombresDe(adjudicatarios) || "sin adjudicatario publicado"}`;
  const seleccion: Resultado =
    (eleccion?.id === pursuit.id ? eleccion.valor : null) ?? sugerido ?? "lost";
  const motivoSugerido = motivoSugeridoDe(pursuit);
  const codigo: MotivoPerdida | "" =
    (motivoElegido?.id === pursuit.id ? motivoElegido.valor : null) ?? motivoSugerido ?? "";
  const pidiendoMotivo = puedeCerrar && perdidaAbierta === pursuit.id;

  const cerrar = async (outcome: Resultado) => {
    if (outcome === "lost" && !codigo) return;
    try {
      await update.mutateAsync({
        outcome,
        // El importe adjudicado es el del contrato, así que sólo acompaña a
        // «ganada»: en una perdida ese número es del competidor.
        ...(outcome === "won"
          ? { awarded_amount_eur: adjudicacion.importe_total ?? null }
          : { outcome_reason_code: codigo || null }),
        outcome_reason: motivo,
        expected_version: pursuit.version,
      });
      toast.success(outcome === "won" ? "Oportunidad cerrada como ganada" : "Oportunidad cerrada como perdida");
    } catch {
      // El aviso lo da el global de mutaciones, con el título del hook (D6).
    }
  };

  const retirar = async () => {
    try {
      await update.mutateAsync({ status: "withdrawn", expected_version: pursuit.version });
      toast.success("Oportunidad retirada");
    } catch {
      // El aviso lo da el global de mutaciones, con el título del hook (D6).
    }
  };

  // Sin `expected_version`: confirmar la fila no toca columnas de la
  // oportunidad (solo anota un evento), así que no compite con otra edición.
  const confirmarFila = async (fila_acta: FilaActaRef) => {
    try {
      await confirmacion.mutateAsync({ fila_acta });
      toast.success("Tu empresa queda marcada en el acta");
    } catch {
      // El aviso lo da el global de mutaciones, con el título del hook (D6).
    }
  };

  const selectorMotivo = (
    <div className="space-y-1">
      <label htmlFor={motivoId} className={ETIQUETA_CAMPO}>
        Motivo de la pérdida
      </label>
      <select
        id={motivoId}
        value={codigo}
        onChange={(event) =>
          setMotivoElegido({ id: pursuit.id, valor: event.target.value as MotivoPerdida | "" })
        }
        disabled={update.isPending}
        aria-describedby={codigo && codigo === motivoSugerido ? `${motivoId}-ayuda` : undefined}
        className="h-9 w-full max-w-xs rounded-md border border-input bg-card px-2 text-campo transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
      >
        <option value="">Elige un motivo</option>
        {MOTIVOS.map((opcion) => (
          <option key={opcion.codigo} value={opcion.codigo}>
            {opcion.etiqueta}
          </option>
        ))}
      </select>
      {codigo && codigo === motivoSugerido && (
        <p id={`${motivoId}-ayuda`} className={AYUDA_CAMPO}>
          Propuesto por las puntuaciones del acta: cámbialo si no es así.
        </p>
      )}
    </div>
  );

  return (
    // El énfasis es el borde primario sobre la superficie de siempre, no un
    // relleno de color (regla de superficies de `console/panel`).
    <section
      className={cn(SUPERFICIE_PANEL, TONO_PANEL.accent, "mb-4 px-4 py-3.5")}
      aria-labelledby="adjudicacion-detectada-titulo"
    >
      <h3 id="adjudicacion-detectada-titulo" className="mb-2.5 text-tf-body font-semibold">
        Este expediente ya se adjudicó
      </h3>

      <ul className="mb-3 space-y-1.5">
        {adjudicatarios.map((a, indice) => (
          <li key={`${a.nif ?? a.nombre}-${indice}`} className="text-tf-body">
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
        <p className="mb-3 text-tf-meta">
          Importe total adjudicado:{" "}
          <span className="font-semibold">{formatCurrency(adjudicacion.importe_total)}</span>
        </p>
      )}

      {adjudicacion.puntuaciones && (
        <div className="mb-3">
          <PuntuacionesActa
            key={pursuit.id}
            pursuit={pursuit}
            puntuaciones={adjudicacion.puntuaciones}
            onConfirmarFila={(fila) => void confirmarFila(fila)}
            confirmando={confirmacion.isPending}
          />
        </div>
      )}

      {puedeCerrar && sugerido ? (
        <div className="space-y-2.5">
          <fieldset className="border-0 p-0">
            <legend className="mb-1.5 text-tf-meta text-muted-foreground">
              Por el NIF de tu organización, esto parece una oportunidad{" "}
              <span className="font-medium text-foreground">
                {sugerido === "won" ? "ganada" : "perdida"}
              </span>
              . Cámbialo si no es así: el cierre lo confirmas tú.
            </legend>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
              {(["won", "lost"] as const).map((opcion) => (
                <label key={opcion} className="flex items-center gap-1.5 text-tf-body">
                  <input
                    type="radio"
                    name={`adjudicacion-resultado-${pursuit.id}`}
                    value={opcion}
                    checked={seleccion === opcion}
                    onChange={() => setEleccion({ id: pursuit.id, valor: opcion })}
                    disabled={update.isPending}
                    className="h-3.5 w-3.5 accent-primary"
                    // El `<label>` que envuelve al input ya le da nombre en el
                    // navegador, pero `jsx-a11y/control-has-associated-label` no
                    // puede verlo: el texto llega por `{ETIQUETA[opcion]}` y la
                    // regla es estática. El `aria-label` lo dice explícitamente
                    // y coincide con lo que se lee, así que no hay dos nombres.
                    aria-label={ETIQUETA[opcion]}
                  />
                  {ETIQUETA[opcion]}
                </label>
              ))}
            </div>
          </fieldset>
          {seleccion === "lost" && selectorMotivo}
          <Button
            size="sm"
            disabled={update.isPending || (seleccion === "lost" && !codigo)}
            onClick={() => void cerrar(seleccion)}
          >
            {seleccion === "won" ? "Confirmar como ganada" : "Confirmar como perdida"}
          </Button>
        </div>
      ) : puedeCerrar ? (
        <div className="space-y-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={update.isPending} onClick={() => void cerrar("won")}>
              Cerrar como ganada
            </Button>
            {/* Abre el motivo debajo en vez de cerrar: una pérdida sin motivo
                es un 422, y el foco se queda en este botón. */}
            <Button
              size="sm"
              variant="outline"
              disabled={update.isPending}
              aria-expanded={pidiendoMotivo}
              aria-controls={`${motivoId}-perdida`}
              onClick={() => setPerdidaAbierta(pidiendoMotivo ? null : pursuit.id)}
            >
              Cerrar como perdida
            </Button>
            <span className="text-tf-micro text-muted-foreground">
              El resultado lo decides tú: TenderFlow no sabe cuál de estas empresas es la tuya.
            </span>
          </div>
          {pidiendoMotivo && (
            <div id={`${motivoId}-perdida`} className="space-y-2.5">
              {selectorMotivo}
              <Button size="sm" disabled={update.isPending || !codigo} onClick={() => void cerrar("lost")}>
                Confirmar como perdida
              </Button>
            </div>
          )}
        </div>
      ) : adjudicacion.cierre_pendiente ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-tf-meta text-muted-foreground">
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
        <p className="text-tf-meta text-muted-foreground">
          Esta oportunidad ya está cerrada. La adjudicación se muestra como contexto.
        </p>
      )}
    </section>
  );
}
