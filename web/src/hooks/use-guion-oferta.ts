"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiMutate } from "@/lib/api-client";
import type { GuionCriterio, GuionOferta, PuntoGuion } from "@/lib/api-types";
import { registrarEvento, tramoDeCriterios } from "@/lib/analytics";
import { guionKeys } from "@/lib/query-keys";

export type { GuionCriterio, GuionOferta, PuntoGuion };

/**
 * F2.6 — guion de la oferta técnica por criterio (D33: esquema, no prosa).
 *
 * La API lo expone como `POST` porque **genera**: cuesta una llamada al LLM y
 * consume presupuesto de la organización. Por eso aquí no hay `useQuery` que
 * lo pida al montar —abrir la pestaña IA tres veces serían tres llamadas— sino
 * una mutación que se lanza con un botón y deja el resultado en la caché.
 *
 * La lectura (`guion`) sólo mira esa caché: nunca pide nada por su cuenta. El
 * backend ya cachea por firma de ficha y documentos, así que regenerar sin que
 * haya cambiado el pliego devuelve el mismo guion sin coste.
 */
export function useGuionOferta(licitacionId: string) {
  const queryClient = useQueryClient();

  const guion = useQuery<GuionOferta>({
    queryKey: guionKeys.detail(licitacionId),
    // Nunca se ejecuta (`enabled: false`); existe porque `useQuery` exige una.
    queryFn: () => Promise.reject(new Error("El guion sólo se genera a petición")),
    enabled: false,
    staleTime: Infinity,
  });

  const generar = useMutation({
    mutationFn: () =>
      apiMutate<GuionOferta>(
        "POST",
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/guion`,
      ),
    onSuccess: (resultado) => {
      queryClient.setQueryData(guionKeys.detail(licitacionId), resultado);
      // Sólo cuenta como generado un guion con contenido: `sin_guion` es el
      // pliego diciendo que no hay criterios, no uso de la herramienta.
      const criterios = resultado.criterios ?? [];
      if (criterios.length > 0) {
        registrarEvento("guion_generado", { criterios: tramoDeCriterios(criterios.length) });
      }
    },
  });

  return { guion: guion.data ?? null, generar };
}

/**
 * El guion en Markdown, para descargar.
 *
 * Es formato, no contenido: cada línea sale de un campo de la respuesta, con
 * la misma forma que `services/rag/guion_oferta.py::a_markdown` —la cita como
 * referencia a documento y página, no como el texto citado—. `nombreDoc`
 * resuelve el id del documento a su nombre de fichero cuando se conoce.
 */
export function guionAMarkdown(
  guion: GuionOferta,
  nombreDoc: (documentoId: number) => string = (id) => `doc ${id}`,
): string {
  const lineas = [`# Guion de la oferta técnica — ${guion.licitacion_id}`, ""];
  if (guion.sin_guion) {
    lineas.push(`_${guion.sin_guion}_`);
    return lineas.join("\n");
  }
  for (const criterio of guion.criterios ?? []) {
    const peso = criterio.peso_pct != null ? ` (${criterio.peso_pct} puntos)` : "";
    lineas.push(`## ${criterio.criterio}${peso}`, "");
    for (const punto of criterio.puntos ?? []) {
      const refs = (punto.evidencia ?? [])
        .map((cita) => `${nombreDoc(cita.documento_id)} p. ${cita.page_number}`)
        .join(", ");
      const marca = punto.sin_base ? " _[sin base en el pliego]_" : refs ? ` _(${refs})_` : "";
      lineas.push(`- ${punto.texto}${marca}`);
    }
    lineas.push("");
  }
  return lineas.join("\n");
}
