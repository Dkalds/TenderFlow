"use client";

import {
  CartesianGrid,
  Cell,
  Label,
  LabelList,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { CAJA_TOOLTIP } from "@/components/charts/chart-tooltip";
import type { Schemas } from "@/lib/api-types";
import { CHART_SERIES } from "@/lib/chart-colors";
import { formatCompactCurrency, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

/* ── Mapa de competidores ──────────────────────────────────────── */

export const ALTO_MAPA_COMPETIDORES = 380;

export type LenteMapa = "precio" | "clientes";

export interface PuntoMapaCompetidor {
  nombre: string;
  x: number;
  y: number;
  /** Cuota del importe: el tamaño del punto. */
  cuota: number;
  /** Nombre corto junto al punto; vacío en los que no destacan. */
  etiqueta: string;
  seleccionado: boolean;
  vigilada: boolean;
  empresa: Schemas["CompetitorEntry"];
}

export type Cuadrante = "arribaIzquierda" | "arribaDerecha" | "abajoIzquierda" | "abajoDerecha";

/**
 * Qué cruza cada lente y cómo se llama cada cuarto del plano. El cuadrante
 * destacado es el que conviene mirar primero: quien gana contratos grandes
 * bajando mucho el precio, o quien vive de un solo cliente.
 */
const LENTES: Record<
  LenteMapa,
  { ejeX: string; ejeY: string; cuadrantes: Record<Cuadrante, string>; destacado: Cuadrante }
> = {
  precio: {
    ejeX: "Baja media: cuánto por debajo del presupuesto gana",
    ejeY: "Importe medio (escala logarítmica)",
    cuadrantes: {
      arribaIzquierda: "Contratos grandes, baja contenida",
      arribaDerecha: "Contratos grandes, baja agresiva",
      abajoIzquierda: "Contratos pequeños, baja contenida",
      abajoDerecha: "Contratos pequeños, baja agresiva",
    },
    destacado: "arribaDerecha",
  },
  clientes: {
    ejeX: "Órganos distintos a los que adjudica",
    ejeY: "Peso de su primer cliente",
    cuadrantes: {
      arribaIzquierda: "Pocos clientes y uno manda",
      arribaDerecha: "Muchos clientes y uno manda",
      abajoIzquierda: "Pocos clientes, repartidos",
      abajoDerecha: "Cartera repartida",
    },
    destacado: "arribaIzquierda",
  },
};

const POSICION_ETIQUETA: Record<
  Cuadrante,
  "insideTopLeft" | "insideTopRight" | "insideBottomLeft" | "insideBottomRight"
> = {
  arribaIzquierda: "insideTopLeft",
  arribaDerecha: "insideTopRight",
  abajoIzquierda: "insideBottomLeft",
  abajoDerecha: "insideBottomRight",
};

const CUADRANTES: Cuadrante[] = ["arribaIzquierda", "arribaDerecha", "abajoIzquierda", "abajoDerecha"];

/**
 * Los lados de un cuadrante que tocan las medianas; los otros dos van al borde.
 *
 * En `ReferenceArea` el lado que falta se va al borde del **lienzo**, no del
 * valor: sin `x2` llega al borde derecho, y sin `y1` al borde de arriba, porque
 * el eje Y crece hacia arriba y los píxeles hacia abajo. Por eso un cuadrante
 * de arriba lleva `y2` (su suelo) y uno de abajo lleva `y1` (su techo).
 */
export function ladosDe(cuadrante: Cuadrante, medianaX: number, medianaY: number) {
  return {
    ...(cuadrante.endsWith("Derecha") ? { x1: medianaX } : { x2: medianaX }),
    ...(cuadrante.startsWith("arriba") ? { y2: medianaY } : { y1: medianaY }),
  };
}

function TooltipEmpresa({ punto, lente }: { punto: PuntoMapaCompetidor; lente: LenteMapa }) {
  const e = punto.empresa;
  return (
    <div className={CAJA_TOOLTIP}>
      <p className="max-w-[22rem] font-medium text-pretty">{punto.nombre}</p>
      {lente === "precio" ? (
        <p className="tf-tnum text-muted-foreground">
          Baja media {formatPercent(punto.x)} · importe medio {formatCurrency(punto.y)}
        </p>
      ) : (
        <p className="tf-tnum text-muted-foreground">
          {formatNumber(punto.x)} órganos · el primero pesa el {formatPercent(punto.y)}
        </p>
      )}
      <p className="tf-tnum text-muted-foreground">
        Cuota {formatPercent(e.cuota)} · {formatNumber(e.count)} adjudicaciones
      </p>
      {/* Sin dato de ofertantes no hay porcentaje que dar: un «0,0 %» aquí se
          lee como «nunca gana sin competencia», que es lo contrario de «no lo
          sabemos». */}
      <p className="tf-tnum text-muted-foreground">
        Gana sin competencia:{" "}
        {e.pct_monopolio == null ? "sin dato de ofertantes" : formatPercent(e.pct_monopolio)}
      </p>
      {punto.vigilada && <p className="font-medium text-foreground">La vigilas</p>}
    </div>
  );
}

/**
 * Cada empresa es un punto en el plano de la lente, con su cuota como tamaño.
 * Las medianas de los puntos dibujados parten el plano en cuatro perfiles.
 */
export function CompetidoresMapaChart({
  puntos,
  lente,
  medianaX,
  medianaY,
  onEmpresaClick,
}: {
  puntos: PuntoMapaCompetidor[];
  lente: LenteMapa;
  medianaX: number | null;
  medianaY: number | null;
  onEmpresaClick: (nombre: string) => void;
}) {
  const config = LENTES[lente];
  const conMedianas = medianaX != null && medianaY != null;
  return (
    <ChartErrorBoundary>
      <ResponsiveContainer width="100%" height={ALTO_MAPA_COMPETIDORES}>
        {/* `key`: al cambiar de lente cambian las dos escalas (una es
            logarítmica); el gráfico se monta de nuevo en vez de interpolar
            entre dos planos que no tienen nada que ver. */}
        <ScatterChart key={lente} accessibilityLayer margin={{ top: 12, right: 28, bottom: 26, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
          {lente === "precio" ? (
            <XAxis
              type="number"
              dataKey="x"
              name="Baja media"
              domain={[(min: number) => Math.min(0, Math.floor(min)), "dataMax"]}
              tick={{ fontSize: 11 }}
              tickFormatter={(v: number) => formatPercent(v, 0)}
            >
              <Label value={config.ejeX} position="bottom" offset={6} fontSize={11} className="fill-muted-foreground" />
            </XAxis>
          ) : (
            <XAxis
              type="number"
              dataKey="x"
              name="Órganos"
              domain={[0, "dataMax"]}
              allowDecimals={false}
              tick={{ fontSize: 11 }}
              tickFormatter={(v: number) => formatNumber(v)}
            >
              <Label value={config.ejeX} position="bottom" offset={6} fontSize={11} className="fill-muted-foreground" />
            </XAxis>
          )}
          {lente === "precio" ? (
            <YAxis
              type="number"
              dataKey="y"
              name="Importe medio"
              scale="log"
              domain={["auto", "auto"]}
              tick={{ fontSize: 11 }}
              tickFormatter={(v: number) => formatCompactCurrency(v)}
              width={72}
            />
          ) : (
            <YAxis
              type="number"
              dataKey="y"
              name="Peso del primer cliente"
              domain={[0, 100]}
              tick={{ fontSize: 11 }}
              tickFormatter={(v: number) => formatPercent(v, 0)}
              width={72}
            />
          )}
          <ZAxis type="number" dataKey="cuota" name="Cuota" range={[50, 520]} />
          {conMedianas && (
            <>
              {CUADRANTES.map((cuadrante) => {
                const destacado = cuadrante === config.destacado;
                return (
                  <ReferenceArea
                    key={cuadrante}
                    {...ladosDe(cuadrante, medianaX, medianaY)}
                    fill={CHART_SERIES[0]}
                    fillOpacity={destacado ? 0.06 : 0}
                    stroke="none"
                    label={{
                      value: config.cuadrantes[cuadrante],
                      position: POSICION_ETIQUETA[cuadrante],
                      fontSize: 11,
                      className: destacado ? "fill-primary" : "fill-muted-foreground",
                    }}
                  />
                );
              })}
              <ReferenceLine x={medianaX} strokeDasharray="4 4" className="stroke-muted-foreground" />
              <ReferenceLine y={medianaY} strokeDasharray="4 4" className="stroke-muted-foreground" />
            </>
          )}
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            content={({ payload }) => {
              if (!payload?.[0]) return null;
              return <TooltipEmpresa punto={payload[0].payload as PuntoMapaCompetidor} lente={lente} />;
            }}
          />
          <Scatter
            data={puntos}
            shape="circle"
            legendType="none"
            className="cursor-pointer"
            // Sin animación de entrada: es una medida, no algo que se mueva.
            isAnimationActive={false}
            onClick={(punto: unknown) => {
              const nodo = punto as { nombre?: string; payload?: { nombre?: string } } | undefined;
              const nombre = nodo?.nombre ?? nodo?.payload?.nombre;
              if (nombre) onEmpresaClick(nombre);
            }}
          >
            {/* A la derecha, en una línea: encima del punto recharts parte el
                nombre al ancho de la burbuja y lo apila sobre las vecinas. */}
            <LabelList dataKey="etiqueta" position="right" fontSize={11} className="fill-foreground" />
            {puntos.map((punto) => (
              <Cell
                key={punto.nombre}
                fill={punto.seleccionado ? "hsl(var(--primary))" : CHART_SERIES[0]}
                fillOpacity={punto.seleccionado ? 1 : 0.75}
                stroke={
                  punto.seleccionado ? "hsl(var(--primary))" : punto.vigilada ? "hsl(var(--foreground))" : "none"
                }
                strokeWidth={punto.seleccionado ? 3 : punto.vigilada ? 2 : 0}
              />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </ChartErrorBoundary>
  );
}
