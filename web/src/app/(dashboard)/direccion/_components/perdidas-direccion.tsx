/**
 * F3.1 cortado para dirección: por qué se pierde, y cuánto de eso se sabe.
 *
 * El reparto lo publica el backend a partir de `perdidas_n_minimo` pérdidas;
 * por debajo llega vacío y aquí se dice cuántas faltan. Debajo, la higiene del
 * dato: cuántas pérdidas de la ventana no tienen motivo, que es lo que dice
 * cuánto se puede creer el reparto, y cuáles son, para codificarlas. Antes era
 * una tarjeta de arriba —un porcentaje de «pérdidas con motivo»— y medía si el
 * equipo rellena el formulario, no el negocio.
 */
import Link from "next/link";

import { Panel, PanelTitle, SectionTitle } from "@/components/console/panel";
import type { Schemas } from "@/lib/api-types";
import { etiquetaMotivo } from "@/lib/motivos-perdida";
import { formatNumber } from "@/lib/utils";

type Cuadro = Schemas["CuadroDireccion"];

function RepartoMotivos({ cuadro }: { cuadro: Cuadro }) {
  const filas = cuadro.perdidas_por_motivo ?? [];
  if (filas.length === 0) {
    return (
      <p role="status" className="text-tf-meta leading-normal text-muted-foreground">
        El reparto se publica a partir de {cuadro.perdidas_n_minimo} pérdidas; en este periodo hay{" "}
        {formatNumber(cuadro.perdidas ?? 0)}. Con menos, el porcentaje diría más del azar que del motivo.
      </p>
    );
  }
  return (
    <ul className="space-y-1.5" aria-label="Pérdidas por motivo">
      {filas.map((fila) => (
        <li key={fila.motivo} className="grid grid-cols-[minmax(0,9rem)_1fr_80px] items-center gap-3">
          <span className="truncate text-tf-meta">{etiquetaMotivo(fila.motivo)}</span>
          <svg className="h-3 w-full" viewBox="0 0 100 1" preserveAspectRatio="none" aria-hidden="true">
            <rect className="fill-secondary/60" width="100" height="1" />
            <rect
              className={fila.motivo === "sin_codificar" ? "fill-muted-foreground/40" : "fill-destructive/60"}
              height="1"
              width={Math.max(1, fila.pct * 100)}
            />
          </svg>
          <span className="tf-tnum text-right text-tf-meta">
            <span className="font-semibold">{Math.round(fila.pct * 100)} %</span>
            <span className="text-muted-foreground"> · {formatNumber(fila.n)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function SinMotivo({ cuadro }: { cuadro: Cuadro }) {
  const sinMotivo = cuadro.perdidas_sin_motivo ?? 0;
  if (sinMotivo === 0) return null;
  const muestra = cuadro.perdidas_sin_motivo_muestra ?? [];
  return (
    <div className="mt-4 border-t border-border/40 pt-3">
      <SectionTitle hint={`${formatNumber(sinMotivo)} de ${formatNumber(cuadro.perdidas ?? 0)}`}>
        Pérdidas sin motivo codificado
      </SectionTitle>
      <ul className="space-y-1 text-tf-meta">
        {muestra.map((oportunidad) => (
          <li key={oportunidad.pursuit_id} className="flex items-baseline justify-between gap-3">
            <Link href={`/oportunidades/${oportunidad.pursuit_id}`} className="min-w-0 truncate hover:underline">
              {oportunidad.titulo ?? oportunidad.licitacion_id}
            </Link>
            <span className="flex-none text-tf-micro text-muted-foreground">Codificar el motivo</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function PerdidasDireccion({ cuadro }: { cuadro: Cuadro }) {
  return (
    <Panel>
      <PanelTitle as="h2" title="Por qué perdemos" hint="Pérdidas cerradas en el periodo" />
      <RepartoMotivos cuadro={cuadro} />
      <SinMotivo cuadro={cuadro} />
    </Panel>
  );
}
