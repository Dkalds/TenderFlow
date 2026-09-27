/**
 * F4.2 — las cifras del cuadro de mando y lo que las sostiene.
 *
 * **Presenta, no calcula** (ADR-014, invariante 1 de `web/AGENTS.md`): el
 * valor, la `n`, el mínimo, el universo y la nota vienen ya resueltos del
 * backend. Por debajo del mínimo el backend manda `valor: null` con una nota
 * «Sin base: …», y aquí se enseña esa nota en el sitio de la cifra — nunca un
 * cero ni un «—» mudo.
 *
 * Las cifras van en la rejilla de 1 px de `StatStrip` (el KPI de la casa), pero
 * en celdas propias y no en `StatCell`: cada una arrastra su nota y su universo,
 * y `StatCell` recorta la pista a una línea, justo lo que no se puede perder.
 */
import { Panel, PanelEmpty, PanelTitle, ROTULO_DATO } from "@/components/console/panel";
import type { Schemas } from "@/lib/api-types";
import { RadarQualityResumen } from "@/components/pursuits/radar-quality";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { etiquetaMotivo } from "@/lib/motivos-perdida";
import { cn, formatCurrency, formatNumber } from "@/lib/utils";

type Tarjeta = Schemas["TarjetaMetrica"];
type Cuadro = Schemas["CuadroDireccion"];

/** La cifra con su unidad. `pct` llega como fracción 0-1. */
export function formatoTarjeta(tarjeta: Tarjeta): string | null {
  if (tarjeta.valor == null) return null;
  switch (tarjeta.unidad) {
    case "eur":
      return formatCurrency(tarjeta.valor);
    case "dias":
      return `${formatNumber(Math.round(tarjeta.valor))} días`;
    case "pct":
      return `${Math.round(tarjeta.valor * 100)} %`;
  }
}

function TarjetaCifra({ tarjeta }: { tarjeta: Tarjeta }) {
  const cifra = formatoTarjeta(tarjeta);
  return (
    <li className="flex min-w-0 flex-col gap-1 bg-card px-3.5 py-2.5">
      <h3 className={ROTULO_DATO}>{tarjeta.etiqueta}</h3>
      {cifra != null ? (
        <p className="tf-tnum text-tf-title font-semibold">{cifra}</p>
      ) : (
        <p className="text-tf-body font-medium">Sin base</p>
      )}
      {tarjeta.nota ? <p className="text-tf-meta text-muted-foreground">{tarjeta.nota}</p> : null}
      <p className="mt-auto text-tf-micro text-muted-foreground">
        {tarjeta.universo} n = {formatNumber(tarjeta.n)}
        {tarjeta.n_minimo > 1 ? ` (mínimo ${tarjeta.n_minimo})` : ""}.
      </p>
    </li>
  );
}

export function TarjetasDireccion({ tarjetas }: { tarjetas: Tarjeta[] }) {
  if (tarjetas.length === 0) return null;
  return (
    <section aria-labelledby="direccion-resumen" className="flex flex-col gap-2">
      <h2 id="direccion-resumen" className="text-tf-body font-semibold">
        Resumen
      </h2>
      <ul
        className="grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-border/60 bg-border/60 sm:grid-cols-2 xl:grid-cols-4"
        aria-label="Cifras de dirección"
      >
        {tarjetas.map((tarjeta) => (
          <TarjetaCifra key={tarjeta.clave} tarjeta={tarjeta} />
        ))}
      </ul>
    </section>
  );
}

/**
 * F3.1 cortado para dirección. El backend devuelve la lista vacía por debajo
 * de `perdidas_n_minimo`; la cifra «Pérdidas con motivo codificado» ya dice
 * cuántas hay, así que aquí sólo se añade el umbral.
 */
export function PerdidasDireccion({ cuadro }: { cuadro: Cuadro }) {
  const filas = cuadro.perdidas_por_motivo ?? [];
  return (
    <Panel>
      <PanelTitle as="h2" title="Pérdidas por motivo" />
      {filas.length === 0 ? (
        <PanelEmpty
          size="sm"
          hint={`Sin base: el reparto se publica a partir de ${cuadro.perdidas_n_minimo} pérdidas cerradas.`}
        />
      ) : (
        <table className="w-full text-tf-body">
          <caption className="sr-only">Pérdidas por motivo</caption>
          <thead>
            <tr className="text-left">
              <th scope="col" className={cn("pb-1.5", CABECERA_COLUMNA)}>
                Motivo
              </th>
              <th scope="col" className={cn("pb-1.5 text-right", CABECERA_COLUMNA)}>
                Pérdidas
              </th>
              <th scope="col" className={cn("pb-1.5 text-right", CABECERA_COLUMNA)}>
                %
              </th>
            </tr>
          </thead>
          <tbody>
            {filas.map((fila) => (
              <tr key={fila.motivo} className="border-t border-border/40">
                <td className="py-1.5">{etiquetaMotivo(fila.motivo)}</td>
                <td className="tf-tnum py-1.5 text-right">{formatNumber(fila.n)}</td>
                <td className="tf-tnum py-1.5 text-right">{Math.round(fila.pct * 100)} %</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

export function RadarDireccion({ cuadro }: { cuadro: Cuadro }) {
  return (
    <Panel>
      <PanelTitle as="h2" title="Precisión del Radar por banda" />
      <RadarQualityResumen calidad={cuadro.radar_quality} />
    </Panel>
  );
}
