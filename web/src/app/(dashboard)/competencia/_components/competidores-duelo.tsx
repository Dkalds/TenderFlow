"use client";

/**
 * Cara a cara: dos empresas, ocho medidas, en mariposa.
 *
 * La del perfil abierto crece hacia la izquierda y la otra hacia la derecha,
 * cada barra a escala de la mayor de las dos, con la cifra exacta al lado.
 * Sustituye al radar, que normalizaba seis ejes de unidades distintas contra
 * el máximo del mercado y pedía marcar dos casillas en una tabla, bajar y
 * cambiar de pestaña para verlo.
 *
 * La segunda empresa se elige con «Comparar» en cualquier fila del ranking.
 */

import { X } from "lucide-react";

import { Panel, PanelTitle } from "@/components/console/panel";
import { Pista } from "@/components/ui/pista";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { CHART_SERIES } from "@/lib/chart-colors";
import { cn, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import type { FilaDuelo, MedidaDuelo } from "../_hooks/competidores-series";
import { Ala, Muestra } from "./dibujos";

const ofertas = (valor: number) => valor.toFixed(1).replace(".", ",");

const MEDIDAS: Record<MedidaDuelo, { rotulo: string; formato: (valor: number) => string }> = {
  cuota: { rotulo: "Cuota del importe", formato: (v) => formatPercent(v) },
  count: { rotulo: "Adjudicaciones", formato: (v) => formatNumber(v) },
  importe_medio: { rotulo: "Importe medio", formato: (v) => formatCurrency(v) },
  baja_media: { rotulo: "Baja media", formato: (v) => formatPercent(v) },
  ofertas_medias: { rotulo: "Ofertas por expediente", formato: ofertas },
  pct_monopolio: { rotulo: "Gana sin competencia", formato: (v) => formatPercent(v) },
  n_organos: { rotulo: "Órganos distintos", formato: (v) => formatNumber(v) },
  pct_top_organo: { rotulo: "Peso del primer cliente", formato: (v) => formatPercent(v) },
};

function Cifra({ valor, formato, mayor }: { valor: number | null; formato: (v: number) => string; mayor: boolean }) {
  if (valor == null) return <span className="w-20 shrink-0 text-tf-meta text-muted-foreground">sin dato</span>;
  return <span className={cn("tf-tnum w-20 shrink-0 text-tf-meta", mayor && "font-semibold")}>{formato(valor)}</span>;
}

export function CompetidoresDuelo({
  nombreA,
  nombreB,
  filas,
  onQuitar,
}: {
  /** La empresa del perfil abierto. */
  nombreA: string;
  /** La elegida con «Comparar». */
  nombreB: string;
  filas: FilaDuelo[];
  onQuitar: () => void;
}) {
  return (
    <Panel>
      <PanelTitle
        title="Cara a cara"
        hint="cada barra, a escala de la mayor de las dos · cambia la segunda con «Comparar» en el ranking"
        actions={
          <button
            type="button"
            onClick={onQuitar}
            className="tf-pressable inline-flex h-6 items-center gap-1 rounded-md border border-border/60 px-1.5 text-tf-micro font-medium text-muted-foreground hover:text-foreground"
          >
            <X className="h-3 w-3" aria-hidden="true" />
            Quitar
          </button>
        }
      />
      {/* `table-fixed`: con el reparto automático, un nombre largo en la
          cabecera se quedaba con el ancho y dejaba el ala de enfrente a cero. */}
      <Table className="table-fixed">
        <caption className="sr-only">
          Comparación de {nombreA} y {nombreB}
        </caption>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[38%]">
              <span className="flex min-w-0 items-center justify-end gap-1.5">
                <Pista contenido={nombreA}>
                  <span className="min-w-0 truncate">{nombreA}</span>
                </Pista>
                <Muestra color={CHART_SERIES[0]} className="h-2 w-2" />
              </span>
            </TableHead>
            <TableHead className="w-[24%] text-center">Medida</TableHead>
            <TableHead className="w-[38%]">
              <span className="flex min-w-0 items-center gap-1.5">
                <Muestra color={CHART_SERIES[1]} className="h-2 w-2" />
                <Pista contenido={nombreB}>
                  <span className="min-w-0 truncate">{nombreB}</span>
                </Pista>
              </span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {filas.map((fila) => {
            const { rotulo, formato } = MEDIDAS[fila.clave];
            return (
              <TableRow key={fila.clave}>
                <TableCell>
                  <div className="flex items-center justify-end gap-2 text-right">
                    <Cifra valor={fila.a} formato={formato} mayor={fila.mayorA} />
                    <Ala pct={fila.pctA} lado="izquierda" color={CHART_SERIES[0]} />
                  </div>
                </TableCell>
                <TableCell className="text-center text-tf-meta text-muted-foreground">{rotulo}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Ala pct={fila.pctB} lado="derecha" color={CHART_SERIES[1]} />
                    <Cifra valor={fila.b} formato={formato} mayor={fila.mayorB} />
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </Panel>
  );
}
