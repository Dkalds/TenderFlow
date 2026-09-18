"use client";

import { useMutation } from "@tanstack/react-query";
import { apiMutate } from "@/lib/api-client";
import type { ReporteDatoBody, ReporteDatoResult, TipoReporte } from "@/lib/api-types";
import { registrarEvento } from "@/lib/analytics";

export type { ReporteDatoResult, TipoReporte };

/**
 * Tipos de reporte en el orden en que se ofrecen, con su etiqueta.
 *
 * La lista cerrada es la de la API (`services/reportes_dato.py::TipoReporte`):
 * el `Record` sobre `TipoReporte` hace que un tipo nuevo en el contrato no
 * compile hasta que alguien le dé etiqueta aquí.
 */
export const TIPOS_REPORTE: Record<TipoReporte, string> = {
  tecnologia: "Tecnología errónea",
  ccaa: "Comunidad autónoma errónea",
  importe: "Importe erróneo",
  adjudicatario: "Adjudicatario erróneo",
  duplicado: "Expediente duplicado",
  otro: "Otro",
};

/**
 * A qué revisión llega el reporte, dicho para quien lo envía. La clave es la
 * `cola` que devuelve la API (`COLA_POR_TIPO`); una cola que este mapa no
 * conozca se nombra de forma genérica en vez de inventarle un destino.
 */
export const DESTINO_COLA: Record<string, string> = {
  ml_feedback: "la revisión de calidad del dato",
  dedupe: "la revisión de duplicados",
  empresas: "la revisión de empresas",
};

/**
 * F6.2 — «este dato está mal», desde la ficha.
 *
 * La telemetría sale **después** del 201 y sólo con el tipo: ni el expediente
 * ni el comentario viajan (ver `dato_reportado` en `lib/analytics.ts`).
 */
export function useReportarDato(licitacionId: string) {
  return useMutation({
    mutationFn: (body: ReporteDatoBody) =>
      apiMutate<ReporteDatoResult>(
        "POST",
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId)}/reportes`,
        body,
      ),
    onSuccess: (_resultado, body) => {
      registrarEvento("dato_reportado", { tipo: body.tipo });
    },
  });
}
