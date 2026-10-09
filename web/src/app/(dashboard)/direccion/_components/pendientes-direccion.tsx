/**
 * Lo que hay que registrar para que Dirección tenga base.
 *
 * Una organización nueva veía ocho huecos («Sin base» en cada tarjeta, «Sin
 * cierres» en cada corte…), cada uno con su explicación. El motivo de todos es
 * el mismo —no hay cierres suficientes— y tiene arreglo: registrar el
 * resultado de las ofertas presentadas. Así que se dice una vez, con la lista
 * de presentadas sin resultado (`pendientes_resultado_muestra`, de la más
 * antigua a la más reciente) y un enlace a cada una.
 */
import Link from "next/link";

import { Panel, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import type { Schemas } from "@/lib/api-types";
import { formatNumber } from "@/lib/utils";

type Cuadro = Schemas["CuadroDireccion"];

export function PendientesResultado({ cuadro, titulo }: { cuadro: Cuadro; titulo?: string }) {
  const total = cuadro.pendientes_resultado ?? 0;
  const muestra = cuadro.pendientes_resultado_muestra ?? [];
  if (total === 0) return null;
  return (
    <Panel>
      <PanelTitle
        as="h2"
        title={titulo ?? "Presentadas sin resultado"}
        hint={`${formatNumber(total)} hoy, de la más antigua a la más reciente`}
      />
      <ul className="divide-y divide-border/40 text-tf-meta">
        {muestra.map((oportunidad) => (
          <li key={oportunidad.pursuit_id} className="flex items-baseline justify-between gap-3 py-1.5">
            <Link href={`/oportunidades/${oportunidad.pursuit_id}`} className="min-w-0 truncate hover:underline">
              {oportunidad.titulo ?? oportunidad.licitacion_id}
            </Link>
            <span className="tf-tnum flex-none text-tf-micro text-muted-foreground">
              {oportunidad.dias != null ? `presentada hace ${formatNumber(oportunidad.dias)} días` : "sin fecha"}
            </span>
          </li>
        ))}
      </ul>
      {total > muestra.length ? (
        <p className="mt-2 text-tf-micro text-muted-foreground">
          Y {formatNumber(total - muestra.length)} más en Oportunidades.
        </p>
      ) : null}
    </Panel>
  );
}

/** Ni en todo el histórico hay cierres suficientes: el aviso único, con la lista. */
export function SinBaseDireccion({ cuadro }: { cuadro: Cuadro }) {
  const minimo = cuadro.n_minimo ?? 5;
  const cierres = cuadro.cierres_historico ?? 0;
  return (
    <Panel tono="accent">
      <PanelTitle as="h2" title={`Dirección empieza a publicar con ${minimo} cierres`} />
      <p className="text-tf-body">
        Llevas {formatNumber(cierres)} {cierres === 1 ? "oportunidad cerrada" : "oportunidades cerradas"} como
        ganada o perdida. Con menos de {minimo}, una tasa de éxito diría más del azar que del equipo, y por
        eso esta pantalla todavía no enseña ninguna.
      </p>
      <p className="mt-2 text-tf-meta text-muted-foreground">
        {(cuadro.pendientes_resultado ?? 0) > 0
          ? "Cada oferta presentada sin resultado es un cierre que falta: registra cómo acabó y la pantalla se llena sola."
          : "No hay ofertas presentadas esperando resultado: los cierres llegarán al registrar las que se resuelvan."}
      </p>
    </Panel>
  );
}

/** Hay base en el histórico pero no en la ventana elegida. */
export function PocosCierresEnVentana({
  cuadro,
  onVerHistorico,
}: {
  cuadro: Cuadro;
  onVerHistorico: () => void;
}) {
  const minimo = cuadro.n_minimo ?? 5;
  return (
    <Panel>
      <p className="text-tf-body">
        En este periodo hay {formatNumber(cuadro.cierres ?? 0)} cierres; las tasas por tecnología, importe,
        procedimiento y órgano se publican a partir de {minimo}.
      </p>
      <Button variant="outline" size="sm" className="mt-3" onClick={onVerHistorico}>
        Ver el histórico ({formatNumber(cuadro.cierres_historico ?? 0)} cierres)
      </Button>
    </Panel>
  );
}
