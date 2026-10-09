"use client";

/**
 * Retirar como no presentadas las oportunidades que ya no admiten oferta: una
 * desde su fila, o varias de una vez desde la cabecera de «Por cerrar».
 *
 * Es la única acción de la agenda que pasa por un diálogo de confirmación
 * (`porRetirar` es lo que el diálogo enseña): `withdrawn` es un estado terminal
 * y la API no reabre. Vive aparte de `use-agenda-acciones.ts` porque es la
 * única con estado propio —qué se ha pedido retirar, si se está retirando— y
 * con un bucle de escrituras detrás.
 */

import * as React from "react";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/query-feedback";
import { type PipelineAgendaItem, useMoverPursuit } from "@/hooks/use-pursuits";
import { tituloDe } from "../_components/agenda/agenda-texto";

/** Una oportunidad con lo que la API pide para moverla: su id y su versión. */
type Retirable = PipelineAgendaItem & { pursuit_id: number; version: number };

function esRetirable(item: PipelineAgendaItem): item is Retirable {
  return item.pursuit_id != null && item.version != null;
}

/** Los títulos de varias filas en una línea, sin que el aviso se haga un párrafo. */
function titulos(items: readonly PipelineAgendaItem[]): string {
  const visibles = items.slice(0, 3).map(tituloDe);
  const resto = items.length - visibles.length;
  return resto > 0 ? `${visibles.join(" · ")} y ${resto} más` : visibles.join(" · ");
}

export function useAgendaRetirada() {
  const moverPursuit = useMoverPursuit();

  /** Las oportunidades que esperan confirmación para retirarse; vacío si ninguna. */
  const [porRetirar, setPorRetirar] = React.useState<PipelineAgendaItem[]>([]);
  const [retirando, setRetirando] = React.useState(false);

  /**
   * Retira las confirmadas en el diálogo.
   *
   * El motivo va puesto —`no_presentada`— porque es lo que la acción afirma: ya
   * no se puede presentar y no hubo oferta. Van **de una en una**: cada
   * oportunidad lleva su versión y la API las valida por separado, así que una
   * que alguien tocó mientras tanto falla ella sola y las demás se retiran
   * igual. Al acabar se dice cuántas no salieron, y cuáles.
   */
  const confirmarRetirada = React.useCallback(
    async (seleccion: readonly PipelineAgendaItem[]) => {
      const validas = seleccion.filter(esRetirable);
      if (!validas.length) return;
      setRetirando(true);
      const fallidas: PipelineAgendaItem[] = [];
      let primerError: unknown = null;
      for (const item of validas) {
        try {
          await moverPursuit.mutateAsync({
            id: item.pursuit_id,
            status: "withdrawn",
            outcome: "cancelled",
            outcome_reason_code: "no_presentada",
            expected_version: item.version,
          });
        } catch (err) {
          fallidas.push(item);
          primerError ??= err;
        }
      }
      setRetirando(false);
      setPorRetirar([]);

      if (validas.length === 1) {
        if (fallidas.length) {
          toast.error("No se pudo retirar la oportunidad", {
            description: getErrorMessage(primerError, "accion"),
          });
        } else {
          toast.success("Oportunidad retirada como no presentada", {
            description: tituloDe(validas[0]),
          });
        }
        return;
      }
      if (fallidas.length) {
        toast.error(
          `${fallidas.length} de ${validas.length} no se ${fallidas.length === 1 ? "pudo" : "pudieron"} retirar`,
          { description: `${titulos(fallidas)}. ${getErrorMessage(primerError, "accion")}` },
        );
      } else {
        toast.success(`${validas.length} oportunidades retiradas como no presentadas`);
      }
    },
    [moverPursuit],
  );

  return {
    porRetirar,
    pedirRetirada: (items: readonly PipelineAgendaItem[]) => setPorRetirar([...items]),
    cancelarRetirada: () => setPorRetirar([]),
    confirmarRetirada,
    retirando,
  };
}
