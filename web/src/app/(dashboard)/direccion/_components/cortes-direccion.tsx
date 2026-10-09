"use client";

/**
 * F4.2 — dónde ganamos: la tasa de éxito por tecnología, tramo de importe,
 * procedimiento y órgano, en barras.
 *
 * Cada fila lleva tres marcas, todas del backend (ADR-014): la barra es la
 * tasa; la línea fina, su intervalo al 95 % (Wilson); el trazo vertical, la
 * tasa de la organización en la misma ventana. «Por encima» o «por debajo» sólo
 * aparece cuando el intervalo entero queda a un lado de la media
 * (`posicion`): con cinco cierres, veinte puntos de diferencia pueden no ser
 * ninguna.
 *
 * Las filas sin base (menos de `n_minimo` cierres) no se omiten ni se
 * dibujan: van plegadas al pie con sus cierres. En una pyme casi ningún órgano
 * llega a cinco, y una lista larga de «aún no» empujaba el resto de la
 * pantalla fuera de la vista.
 */
import * as React from "react";
import Link from "next/link";

import { Panel, PanelEmpty, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { cn, formatNumber } from "@/lib/utils";
import { enlaceDeCorte, formatoIntervalo, type Corte } from "../_lib/formato";

type Fila = NonNullable<Corte["filas"]>[number];

/** Filas visibles antes de «Ver todas». */
const VISIBLES = 6;

/**
 * Sólo se dice la posición cuando es significativa. `en_linea` —la media cae
 * dentro del margen— no se escribe: repetido en cada fila era ruido, y el
 * trazo de la media dentro de la línea del margen ya lo enseña.
 */
const POSICION = {
  por_encima: { texto: "Por encima de la media", clase: "text-success" },
  por_debajo: { texto: "Por debajo de la media", clase: "text-destructive" },
} as const;

/** Barra, intervalo y media en una sola franja SVG de 0 a 100. */
function BarraCorte({ fila, media }: { fila: Fila; media: number | null | undefined }) {
  const valor = (fila.valor ?? 0) * 100;
  const bajo = (fila.intervalo_bajo ?? fila.valor ?? 0) * 100;
  const alto = (fila.intervalo_alto ?? fila.valor ?? 0) * 100;
  return (
    <svg className="h-4 w-full" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">
      <rect className="fill-secondary/60" width="100" height="10" rx="1" />
      <rect className="fill-primary/55" y="2" height="6" width={Math.max(1, valor)} />
      <line
        className="stroke-foreground/70"
        x1={bajo}
        x2={alto}
        y1="5"
        y2="5"
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
      {media != null ? (
        <line
          className="stroke-foreground"
          x1={media * 100}
          x2={media * 100}
          y1="0"
          y2="10"
          strokeWidth="1.5"
          strokeDasharray="2 1.5"
          vectorEffect="non-scaling-stroke"
        />
      ) : null}
    </svg>
  );
}

function FilaCorte({ corte, fila }: { corte: Corte; fila: Fila }) {
  const nombre = fila.etiqueta ?? fila.clave;
  const destino = enlaceDeCorte(corte.clave, fila.clave);
  const posicion = fila.posicion && fila.posicion !== "en_linea" ? POSICION[fila.posicion] : null;
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 py-1.5 sm:grid-cols-[minmax(0,11rem)_minmax(0,1fr)_auto]">
      <span className="min-w-0 truncate text-tf-meta font-medium">
        {destino ? (
          <Link href={destino} className="hover:underline">
            {nombre}
          </Link>
        ) : (
          nombre
        )}
      </span>
      <span className="order-3 col-span-2 sm:order-none sm:col-span-1">
        <BarraCorte fila={fila} media={corte.media} />
      </span>
      <span className="tf-tnum text-right text-tf-meta">
        <span className="font-semibold">{Math.round((fila.valor ?? 0) * 100)} %</span>
        <span className="text-muted-foreground"> · {formatNumber(fila.n)}</span>
      </span>
      <span className="order-4 col-span-2 text-tf-micro text-muted-foreground sm:col-span-3">
        {fila.intervalo_bajo != null && fila.intervalo_alto != null
          ? `Margen ${formatoIntervalo(fila.intervalo_bajo, fila.intervalo_alto)}`
          : null}
        {posicion ? <span className={cn("font-medium", posicion.clase)}> · {posicion.texto}</span> : null}
      </span>
    </li>
  );
}

function SinBaseCorte({ corte, minimo }: { corte: Corte; minimo: number }) {
  const filas = corte.filas_sin_base ?? [];
  if (filas.length === 0) return null;
  return (
    <details className="mt-2 text-tf-meta text-muted-foreground">
      <summary className="cursor-pointer select-none hover:text-foreground">
        {corte.filas && corte.filas.length > 0 ? "Y " : ""}
        {formatNumber(filas.length)} con menos de {minimo} cierres ({formatNumber(corte.cierres_sin_base ?? 0)}{" "}
        cierres en total)
      </summary>
      <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
        {filas.map((fila) => (
          <li key={fila.clave} className="tf-tnum">
            {fila.etiqueta ?? fila.clave} · {formatNumber(fila.n)}/{minimo}
          </li>
        ))}
      </ul>
    </details>
  );
}

export function CortePanel({ corte, minimo }: { corte: Corte; minimo: number }) {
  const [todas, setTodas] = React.useState(false);
  const filas = corte.filas ?? [];
  const visibles = todas ? filas : filas.slice(0, VISIBLES);
  const titulo = `Por ${corte.titulo.toLowerCase()}`;
  return (
    <Panel>
      <PanelTitle
        as="h3"
        title={titulo}
        hint={corte.media != null ? `Media ${Math.round(corte.media * 100)} %` : undefined}
      />
      {filas.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="Ninguna con base todavía"
          hint={`Una fila se publica a partir de ${minimo} cierres.`}
        />
      ) : (
        <ul className="divide-y divide-border/40" aria-label={`Tasa de éxito ${titulo.toLowerCase()}`}>
          {visibles.map((fila) => (
            <FilaCorte key={fila.clave} corte={corte} fila={fila} />
          ))}
        </ul>
      )}
      {filas.length > VISIBLES ? (
        <Button variant="ghost" size="sm" className="mt-1" onClick={() => setTodas((v) => !v)}>
          {todas ? "Ver menos" : `Ver todas (${formatNumber(filas.length)})`}
        </Button>
      ) : null}
      <SinBaseCorte corte={corte} minimo={minimo} />
    </Panel>
  );
}

export function CortesDireccion({ cortes, minimo }: { cortes: Corte[]; minimo: number }) {
  if (cortes.length === 0) return null;
  return (
    <section aria-labelledby="direccion-cortes" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="direccion-cortes" className="text-tf-body font-semibold">
          Dónde ganamos
        </h2>
        <p className="text-tf-micro text-muted-foreground">
          Barra: tasa de éxito · línea: margen al 95 % · trazo vertical: media de la organización
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {cortes.map((corte) => (
          <CortePanel key={corte.clave} corte={corte} minimo={minimo} />
        ))}
      </div>
    </section>
  );
}
