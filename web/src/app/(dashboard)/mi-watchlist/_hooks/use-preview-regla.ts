"use client";

/**
 * F5.5 — vista previa de ruido de una regla: cuántos expedientes casan hoy y
 * cuántos casaron cada una de las últimas ocho semanas.
 *
 * Todo lo que se pinta viene de `POST /watchlist/rules/preview`: la serie, el
 * umbral y si la regla es ruidosa (`ruido_alto`). El cliente no recalcula la
 * media ni compara con el umbral: el aviso tiene que ser el mismo lo pinte
 * quien lo pinte.
 */

import { useMutation } from "@tanstack/react-query";
import { apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { numeroDeTexto } from "@/lib/forms/valores";
import type { RuleBody } from "./watchlist-rule-types";

export type PreviewRegla = Schemas["PreviewResult"];

const PREVIEW_URL = "/api/v1/watchlist/rules/preview";

export function usePreviewRegla() {
  return useMutation({
    mutationFn: (body: RuleBody) => apiMutate<PreviewRegla>("POST", PREVIEW_URL, body),
  });
}

/** Los cinco campos del alta rápida (`nuevaRegla` en `lib/forms/esquemas.ts`). */
export interface ValoresNuevaRegla {
  keyword: string;
  cpv: string;
  min_importe: string;
  ccaa: string;
  frequency: RuleBody["frequency"];
}

/**
 * El cuerpo de una regla del alta rápida. Lo usan el alta y su vista previa:
 * si cada una lo armara por su cuenta, la previa mediría una regla distinta de
 * la que se guarda.
 */
export function cuerpoDeNuevaRegla(
  { keyword, cpv, min_importe, ccaa, frequency }: ValoresNuevaRegla,
  tecnologiaPrefill: string,
): RuleBody {
  return {
    nombre: keyword.trim(),
    keyword: keyword.trim(),
    cpv: cpv.trim() || null,
    min_importe: numeroDeTexto(min_importe),
    ccaa: ccaa || null,
    frequency,
    active: true,
    // El alta rápida no expone los criterios de S4.4 —se afinan en el panel
    // de edición, sobre una regla que ya tiene conteo con el que comparar—
    // así que viajan a `null`, que es «este criterio no filtra». La única
    // excepción es la tecnología del prefill de la command palette: venía en
    // el ámbito desde el que se pulsó «crear regla», y perderla haría que la
    // regla naciera más ancha de lo que el usuario estaba mirando.
    tecnologia: tecnologiaPrefill || null,
    organo: null,
    procedimiento: null,
    tipo_contrato: null,
    banda_min: null,
    plazo_min_dias: null,
  };
}

/**
 * `ruido_avisado` de `regla_creada`: qué dijo la vista previa **de esta misma
 * regla**. Sin vista previa, o con una de otros criterios, no se sabe y no se
 * manda: contar como «no avisado» a quien no la pidió inflaría el «no».
 */
export function ruidoAvisado(
  previa: { data?: PreviewRegla; variables?: RuleBody },
  body: RuleBody,
): "si" | "no" | undefined {
  if (!previa.data || !previa.variables) return undefined;
  if (JSON.stringify(previa.variables) !== JSON.stringify(body)) return undefined;
  return previa.data.ruido_alto ? "si" : "no";
}
