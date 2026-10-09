"use client";

/**
 * La evolución mensual de las UTE: dos gráficos de columnas, uno sobre otro,
 * que comparten el eje de los meses.
 *
 * Son dos y no uno con dos ejes verticales: con las UTE a un lado y el importe
 * al otro, dónde se cruzan las dos series depende sólo de cómo se eligieron las
 * escalas, y se lee como una relación que el dato no afirma. Aquí cada medida
 * tiene su escala y la dice («máximo 9 en un mes»).
 *
 * Al pasar por un mes los dos gráficos lo señalan a la vez y el rótulo de cada
 * uno da su cifra. El dibujo va oculto al lector de pantalla, que tiene la
 * serie entera en una tabla.
 */

import { useState } from "react";

import { Panel, PanelEmpty, PanelLoading, PanelTitle, ROTULO_DATO } from "@/components/console/panel";
import { CHART_SERIES } from "@/lib/chart-colors";
import { cn, formatCompactCurrency, formatCurrency, formatNumber } from "@/lib/utils";

import type { ColumnaEvolucion, SerieEvolucion } from "../_hooks/utes-series";

/** Alto del contenido, para que la carga y el vacío ocupen lo mismo. */
const ALTO = 164;

/** Lo mínimo que levanta una columna con dato, para que un mes flojo no desaparezca. */
const ALTO_MINIMO = 3;

function Columnas({
  serie,
  medida,
  color,
  activo,
  onActivo,
}: {
  serie: SerieEvolucion;
  medida: "contratos" | "importe";
  color: string;
  activo: number | null;
  onActivo: (indice: number) => void;
}) {
  return (
    <div className="flex h-12 items-end gap-px border-b border-border">
      {serie.columnas.map((columna, i) => {
        const pct = medida === "contratos" ? columna.pctContratos : columna.pctImporte;
        const alto = columna[medida] > 0 ? Math.max(pct, ALTO_MINIMO) : 0;
        return (
          <svg
            key={columna.period}
            className="h-full min-w-0 flex-1"
            viewBox="0 0 10 100"
            preserveAspectRatio="none"
            onPointerEnter={() => onActivo(i)}
          >
            <rect
              x="0"
              y={100 - alto}
              width="10"
              height={alto}
              fill={color}
              fillOpacity={activo == null || activo === i ? 1 : 0.35}
            />
          </svg>
        );
      })}
      <Relleno huecos={serie.relleno} />
    </div>
  );
}

/** Huecos vacíos a la derecha: con pocos meses, las columnas no se ensanchan. */
function Relleno({ huecos }: { huecos: number }) {
  return Array.from({ length: huecos }).map((_, i) => <span key={i} className="min-w-0 flex-1" />);
}

function Rotulo({ nombre, pista }: { nombre: string; pista: string }) {
  return (
    <div className="mb-0.5 flex items-baseline justify-between gap-2">
      <span className={cn("flex-none", ROTULO_DATO)}>{nombre}</span>
      <span className={cn("tf-tnum min-w-0 truncate", ROTULO_DATO)}>{pista}</span>
    </div>
  );
}

function Grafico({ serie }: { serie: SerieEvolucion }) {
  const [activo, setActivo] = useState<number | null>(null);
  const mes: ColumnaEvolucion | undefined = activo == null ? undefined : serie.columnas[activo];

  return (
    <div aria-hidden="true" onPointerLeave={() => setActivo(null)}>
      <Rotulo
        nombre="UTE adjudicadas"
        pista={
          mes
            ? `${mes.etiqueta} · ${formatNumber(mes.contratos)} UTE`
            : `máximo ${formatNumber(serie.maxContratos)} en un mes`
        }
      />
      <Columnas serie={serie} medida="contratos" color={CHART_SERIES[0]} activo={activo} onActivo={setActivo} />
      <div className="mt-2.5">
        <Rotulo
          nombre="Importe"
          pista={
            mes
              ? `${mes.etiqueta} · ${formatCurrency(mes.importe)}`
              : `máximo ${formatCompactCurrency(serie.maxImporte)} en un mes`
          }
        />
      </div>
      <Columnas serie={serie} medida="importe" color={CHART_SERIES[1]} activo={activo} onActivo={setActivo} />
      <div className="mt-1 flex gap-px text-tf-micro text-muted-foreground">
        {serie.columnas.map((columna) => (
          <span key={columna.period} className="relative h-3.5 min-w-0 flex-1">
            {columna.enEje && <span className="tf-tnum absolute left-0 top-0 whitespace-nowrap">{columna.etiqueta}</span>}
          </span>
        ))}
        <Relleno huecos={serie.relleno} />
      </div>
    </div>
  );
}

export function UtesEvolucion({ serie, isLoading }: { serie: SerieEvolucion; isLoading: boolean }) {
  return (
    <Panel className="relative min-w-0">
      <PanelTitle title="Evolución" hint="por mes, dos medidas con el mismo eje" />
      {isLoading ? (
        <PanelLoading height={ALTO} />
      ) : serie.columnas.length === 0 ? (
        <PanelEmpty
          title="Ningún mes con UTE"
          hint="No hay UTE adjudicatarias en el ámbito actual. Amplía las fechas o quita filtros."
          height={ALTO}
        />
      ) : (
        <>
          <Grafico serie={serie} />
          <table className="sr-only">
            <caption>UTE adjudicadas e importe, por mes</caption>
            <thead>
              <tr>
                <th scope="col">Mes</th>
                <th scope="col">UTE adjudicadas</th>
                <th scope="col">Importe</th>
              </tr>
            </thead>
            <tbody>
              {serie.columnas.map((columna) => (
                <tr key={columna.period}>
                  <th scope="row">{columna.etiqueta}</th>
                  <td>{formatNumber(columna.contratos)}</td>
                  <td>{formatCurrency(columna.importe)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Panel>
  );
}
