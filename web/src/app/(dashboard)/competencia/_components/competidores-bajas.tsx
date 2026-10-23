"use client";

/**
 * Bajas medias por órgano, familia CPV o comunidad: dónde se rebaja más para
 * ganar.
 *
 * `GET /competitive/bajas` sobre el ámbito de la barra en lo que el endpoint
 * entiende —comunidad, fechas de adjudicación e importe mínimo—. Lo que no
 * entiende se nombra encima de la tabla: el resto de la pantalla sí lo aplica,
 * y callarlo haría pasar esta tabla por la del mismo ámbito.
 *
 * Cada fila lleva su rango (mínima a máxima) sobre una escala común con la
 * media marcada: dos órganos con la misma media y rangos de 2 y de 40 puntos
 * no se ganan igual. Y la `base` de importe va escrita al pie (C1.1).
 */

import { useState } from "react";

import { Panel, PanelEmpty, PanelError, PanelTitle, Segmented } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useFilterParams } from "@/lib/filters";
import { EMPTY, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import {
  escalaBajas,
  filtrosNoAplicados,
  nombreSegmento,
  OPCIONES_BAJAS,
  posicionEnEscala,
  textoBase,
  type BajaAgregada,
  type BajasPor,
} from "../_hooks/mercado-segmentos";
import { MIN_CONTRATOS_BAJAS, useBajasPorGrupo } from "../_hooks/use-mercado-segmentos";

/** Rango mínima-máxima con la media marcada, sobre la escala de la tabla. */
function RangoBaja({ fila, escala }: { fila: BajaAgregada; escala: { min: number; max: number } }) {
  if (fila.baja_min_pct == null || fila.baja_max_pct == null) return <span className="text-muted-foreground">{EMPTY}</span>;
  const desde = posicionEnEscala(fila.baja_min_pct, escala);
  const hasta = posicionEnEscala(fila.baja_max_pct, escala);
  const media = fila.baja_media_pct != null ? posicionEnEscala(fila.baja_media_pct, escala) : null;
  return (
    <div className="flex items-center gap-2">
      <svg aria-hidden="true" className="h-3 min-w-16 flex-1" viewBox="0 0 100 12" preserveAspectRatio="none">
        <rect y="5" width="100" height="2" className="fill-muted" />
        <rect x={desde} y="3" width={Math.max(0.8, hasta - desde)} height="6" fill="hsl(var(--primary))" fillOpacity="0.35" />
        {media != null && <rect x={Math.max(0, media - 0.75)} y="0" width="1.5" height="12" fill="hsl(var(--foreground))" />}
      </svg>
      <span className="tf-tnum shrink-0 text-tf-micro text-muted-foreground">
        {formatPercent(fila.baja_min_pct, 0)}–{formatPercent(fila.baja_max_pct, 0)}
      </span>
    </div>
  );
}

export function CompetidoresBajas() {
  const [por, setPor] = useState<BajasPor>("organo");
  const filtros = useFilterParams();
  const noAplicados = filtrosNoAplicados(filtros);
  const { data, isLoading, error, refetch } = useBajasPorGrupo(por);
  const items = data?.items ?? [];
  const escala = escalaBajas(items);
  const etiquetaGrupo = OPCIONES_BAJAS.find((opcion) => opcion.value === por)?.label ?? "Grupo";

  return (
    <Panel>
      <PanelTitle
        title="Bajas medias"
        hint="dónde se rebaja más para ganar"
        actions={<Segmented aria-label="Agrupar bajas por" size="xs" value={por} onChange={setPor} options={OPCIONES_BAJAS} />}
        className="flex-wrap"
      />
      {noAplicados.length > 0 && (
        <p className="mb-2 text-tf-meta text-muted-foreground">
          Sigue la comunidad, las fechas de adjudicación y el importe mínimo de la barra; no aplica{" "}
          {noAplicados.join(", ")}.
        </p>
      )}
      {isLoading ? (
        <Skeleton className="h-56 w-full" />
      ) : error ? (
        <PanelError variant="inline" title="No se pudieron cargar las bajas" error={error} onRetry={() => void refetch()} />
      ) : items.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="Ningún grupo con bajas comparables en el ámbito"
          hint={`Cada grupo necesita ${formatNumber(MIN_CONTRATOS_BAJAS)} adjudicaciones o más con presupuesto y adjudicado. Amplía las fechas o quita filtros.`}
        />
      ) : (
        <>
          <Table>
            <caption className="sr-only">Bajas medias por {etiquetaGrupo.toLowerCase()}, de más a menos contratos</caption>
            <TableHeader>
              <TableRow>
                <TableHead>{etiquetaGrupo}</TableHead>
                <TableHead className="text-right">Contratos</TableHead>
                <TableHead className="text-right">Baja media</TableHead>
                <TableHead className="w-[28%] whitespace-nowrap">Rango</TableHead>
                <TableHead className="whitespace-nowrap text-right">Ofertas / exped.</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((fila, i) => (
                <TableRow key={`${fila.grupo_id ?? ""}-${fila.grupo ?? i}`}>
                  <TableCell className="max-w-64 truncate" title={fila.grupo ?? undefined}>
                    {nombreSegmento(por, fila.grupo)}
                    <span className="block text-tf-micro text-muted-foreground">{formatCurrency(fila.importe_total)}</span>
                  </TableCell>
                  <TableCell className="tf-tnum text-right">{formatNumber(fila.contratos)}</TableCell>
                  <TableCell className="tf-tnum text-right font-semibold">{formatPercent(fila.baja_media_pct)}</TableCell>
                  <TableCell>
                    <RangoBaja fila={fila} escala={escala} />
                  </TableCell>
                  <TableCell className="tf-tnum text-right">
                    {formatNumber(fila.ofertas_medias, "es-ES", { decimales: 1 })}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="mt-2 text-tf-micro text-muted-foreground">{textoBase(data?.base)}</p>
        </>
      )}
    </Panel>
  );
}
