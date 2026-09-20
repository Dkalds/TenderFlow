"use client";

/**
 * F5.5 — cuántas alertas habría dado la regla cada semana, y si es demasiadas.
 *
 * Las ocho barras, el umbral y el aviso son la respuesta de
 * `POST /watchlist/rules/preview` tal cual: la escala del dibujo es lo único
 * que se calcula aquí. El aviso lo decide el servidor (`ruido_alto`), no una
 * comparación en cliente, para que diga lo mismo en el alta y en la edición.
 *
 * Accesible sin mirar el dibujo: el SVG es decorativo (`aria-hidden`) y la
 * serie va en una tabla de solo lectura para el lector de pantalla, con el
 * umbral en su pie.
 */

import { AlertTriangle } from "lucide-react";
import { formatDate, formatNumber } from "@/lib/utils";
import type { PreviewRegla } from "../_hooks/use-preview-regla";

const ANCHO = 240;
const ALTO = 56;
const HUECO = 4;

export function VistaPreviaRuido({ preview }: { preview: PreviewRegla }) {
  const serie = preview.serie_semanal ?? [];
  const umbral = preview.umbral_semanal ?? null;
  if (serie.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        {formatNumber(preview.total)} licitación(es) coincidirían hoy. Sin serie semanal que enseñar.
      </p>
    );
  }
  const tope = Math.max(1, umbral ?? 0, ...serie.map((s) => s.n));
  const anchoBarra = (ANCHO - HUECO * (serie.length - 1)) / serie.length;
  const yUmbral = umbral != null ? ALTO - (umbral / tope) * ALTO : null;

  return (
    <figure className="space-y-2 rounded-md border border-border/70 p-3">
      <figcaption className="text-xs font-medium">
        {formatNumber(preview.total)} licitación(es) coincidirían hoy · coincidencias por semana,
        últimas {serie.length}
      </figcaption>
      <svg
        viewBox={`0 0 ${ANCHO} ${ALTO}`}
        className="h-14 w-full max-w-[20rem]"
        aria-hidden="true"
        preserveAspectRatio="none"
      >
        {serie.map((semana, i) => {
          const alto = Math.max((semana.n / tope) * ALTO, semana.n > 0 ? 2 : 0);
          return (
            <rect
              key={semana.semana}
              x={i * (anchoBarra + HUECO)}
              y={ALTO - alto}
              width={anchoBarra}
              height={alto}
              rx={1.5}
              className="fill-primary"
            />
          );
        })}
        {yUmbral != null && (
          <line
            x1={0}
            x2={ANCHO}
            y1={yUmbral}
            y2={yUmbral}
            strokeDasharray="4 3"
            strokeWidth={1}
            className="stroke-muted-foreground"
          />
        )}
      </svg>
      <div className="flex max-w-[20rem] justify-between text-[10.5px] text-muted-foreground">
        <span>{formatDate(serie[0].semana)}</span>
        {umbral != null && <span>- - umbral {formatNumber(umbral)}/semana</span>}
        <span>{formatDate(serie[serie.length - 1].semana)}</span>
      </div>
      <table className="sr-only">
        <caption>Coincidencias por semana</caption>
        <thead>
          <tr>
            <th scope="col">Semana del</th>
            <th scope="col">Coincidencias</th>
          </tr>
        </thead>
        <tbody>
          {serie.map((semana) => (
            <tr key={semana.semana}>
              <td>{formatDate(semana.semana)}</td>
              <td>{semana.n}</td>
            </tr>
          ))}
        </tbody>
        {umbral != null && (
          <tfoot>
            <tr>
              <td colSpan={2}>Umbral de aviso: {umbral} por semana de media.</td>
            </tr>
          </tfoot>
        )}
      </table>
      {preview.ruido_alto && (
        <p role="status" className="flex gap-2 rounded-md border border-warning/30 bg-warning/10 p-2 text-xs text-warning">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>
            De media pasa de {umbral != null ? formatNumber(umbral) : "el umbral de"} coincidencias
            por semana: esta regla va a hacer ruido. Acótala con un CPV, un importe mínimo o una
            comunidad autónoma.
          </span>
        </p>
      )}
    </figure>
  );
}
