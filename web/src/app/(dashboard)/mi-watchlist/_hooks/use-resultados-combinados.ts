"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { watchlistKeys } from "@/lib/query-keys";
import { dedupeMatches } from "./watchlist-matches";
import type { ApiRule, MatchItem } from "./watchlist-rule-types";

/**
 * Las coincidencias de todas las reglas activas, juntas y sin repetir.
 *
 * Un fallo ya no se convierte en lista vacía: con todas las reglas caídas la
 * consulta falla (y la pantalla lo dice), y con alguna caída devuelve lo que
 * respondió más `sinRespuesta`, para avisar de que la lista es parcial. Antes
 * cada error era `[]` y la pantalla decía «Ninguna licitación coincide con tus
 * reglas activas».
 */
export function useResultadosCombinados(activeRules: ApiRule[]) {
  return useQuery<{ items: MatchItem[]; sinRespuesta: number }>({
    queryKey: watchlistKeys.combined(activeRules.map((r) => r.id).join(",")),
    enabled: activeRules.length > 0,
    meta: META_ERROR_EN_LINEA,
    queryFn: async () => {
      const perRule = await Promise.allSettled(
        activeRules.map((rule) =>
          fetchWithAuth<{ items?: MatchItem[] }>(`/api/v1/watchlist/rules/${rule.id}/matches?limit=20`),
        ),
      );
      const respondidas = perRule.flatMap((r) => (r.status === "fulfilled" ? [r.value.items ?? []] : []));
      const fallo = perRule.find((r): r is PromiseRejectedResult => r.status === "rejected");
      if (fallo && respondidas.length === 0) throw fallo.reason;
      return { items: dedupeMatches(respondidas), sinRespuesta: perRule.length - respondidas.length };
    },
  });
}
