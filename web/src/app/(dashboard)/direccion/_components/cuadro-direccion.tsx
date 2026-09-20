/**
 * F4.2 — las tarjetas del cuadro de mando y lo que las sostiene.
 *
 * **Presenta, no calcula** (ADR-014, invariante 1 de `web/AGENTS.md`): el
 * valor, la `n`, el mínimo, el universo y la nota vienen ya resueltos del
 * backend. Por debajo del mínimo el backend manda `valor: null` con una nota
 * «Sin base: …», y aquí se enseña esa nota en el sitio de la cifra — nunca un
 * cero ni un «—» mudo.
 */
import type { Schemas } from "@/lib/api-types";
import { RadarQualityResumen } from "@/components/pursuits/radar-quality";
import { etiquetaMotivo } from "@/lib/motivos-perdida";
import { formatCurrency, formatNumber } from "@/lib/utils";

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
    <li className="border-border/70 flex flex-col gap-1.5 rounded-md border p-3">
      <h3 className="text-muted-foreground text-xs font-medium">{tarjeta.etiqueta}</h3>
      {cifra != null ? (
        <p className="tf-tnum text-xl font-semibold">{cifra}</p>
      ) : (
        <p className="text-sm font-medium">Sin base</p>
      )}
      {tarjeta.nota ? <p className="text-muted-foreground text-xs">{tarjeta.nota}</p> : null}
      <p className="text-muted-foreground mt-auto text-[11px] leading-relaxed">
        {tarjeta.universo} n = {formatNumber(tarjeta.n)}
        {tarjeta.n_minimo > 1 ? ` (mínimo ${tarjeta.n_minimo})` : ""}.
      </p>
    </li>
  );
}

export function TarjetasDireccion({ tarjetas }: { tarjetas: Tarjeta[] }) {
  if (tarjetas.length === 0) return null;
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-medium">Resumen</h2>
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Tarjetas de dirección">
        {tarjetas.map((tarjeta) => (
          <TarjetaCifra key={tarjeta.clave} tarjeta={tarjeta} />
        ))}
      </ul>
    </section>
  );
}

/**
 * F3.1 cortado para dirección. El backend devuelve la lista vacía por debajo
 * de `perdidas_n_minimo`; la tarjeta «Pérdidas con motivo codificado» ya dice
 * cuántas hay, así que aquí sólo se añade el umbral.
 */
export function PerdidasDireccion({ cuadro }: { cuadro: Cuadro }) {
  const filas = cuadro.perdidas_por_motivo ?? [];
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-medium">Pérdidas por motivo</h2>
      {filas.length === 0 ? (
        <p role="status" className="text-muted-foreground text-xs">
          Sin base: el reparto se publica a partir de {cuadro.perdidas_n_minimo} pérdidas cerradas.
        </p>
      ) : (
        <table className="w-full text-xs">
          <caption className="sr-only">Pérdidas por motivo</caption>
          <thead>
            <tr className="text-muted-foreground text-left">
              <th scope="col" className="pb-1.5 font-medium">
                Motivo
              </th>
              <th scope="col" className="pb-1.5 text-right font-medium">
                Pérdidas
              </th>
              <th scope="col" className="pb-1.5 text-right font-medium">
                %
              </th>
            </tr>
          </thead>
          <tbody>
            {filas.map((fila) => (
              <tr key={fila.motivo} className="border-border/50 border-t">
                <td className="py-1.5">{etiquetaMotivo(fila.motivo)}</td>
                <td className="tf-tnum py-1.5 text-right">{formatNumber(fila.n)}</td>
                <td className="tf-tnum py-1.5 text-right">{Math.round(fila.pct * 100)} %</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function RadarDireccion({ cuadro }: { cuadro: Cuadro }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-medium">Precisión del Radar por banda</h2>
      <RadarQualityResumen calidad={cuadro.radar_quality} />
    </section>
  );
}
