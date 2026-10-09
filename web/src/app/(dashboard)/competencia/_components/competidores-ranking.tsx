"use client";

/**
 * El ranking de competidores, con el dibujo dentro de la fila.
 *
 * Cada empresa lleva su cuota como barra, su baja como un punto sobre una
 * escala común a toda la columna, la presión que encuentra (ofertas por
 * expediente) y cuánto gana sin competencia. Son las columnas que se comparan
 * de arriba abajo; en cifras sueltas esa comparación había que hacerla de
 * cabeza.
 *
 * «Tabla completa» devuelve las doce columnas con su cabecera ordenable. Las
 * dos caras tienen un botón real por empresa: el teclado recorre aquí lo que el
 * mapa y el reparto solo ofrecen al ratón.
 */

import { useState } from "react";

import { Panel, PanelEmpty, PanelTitle, Segmented } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { CHART_SERIES } from "@/lib/chart-colors";
import { cn, EMPTY, formatCurrency, formatDate, formatNumber, formatPercent } from "@/lib/utils";

import { escalasRanking } from "../_hooks/competidores-series";
import type { Competitor, Metrica, SortKey } from "../_hooks/competidores-types";
import { esVigilada } from "../_hooks/vigilados";
import { BotonComparar, CompetidorNombre } from "./competidor-nombre";
import { CompetidoresTabla, rowKey } from "./competidores-tabla";
import { BarraPct } from "./dibujos";

export type VistaRanking = "graficos" | "tabla";

const OPCIONES_VISTA: { value: VistaRanking; label: string }[] = [
  { value: "graficos", label: "Con gráficos" },
  { value: "tabla", label: "Tabla completa" },
];

/** Cuántas filas enseña el ranking antes de pedir el resto. */
export const FILAS_RANKING = 12;

/** Un punto sobre la escala común de la columna: dónde cae esta baja de 0 al tope. */
function PuntoEnEscala({ valor, tope }: { valor: number; tope: number }) {
  const pct = tope > 0 ? Math.max(0, Math.min(100, (valor / tope) * 100)) : 0;
  return (
    // Aire a los lados: un punto en el 0 o en el tope se dibuja entero.
    <span aria-hidden="true" className="block min-w-12 flex-1 px-1">
      <svg className="h-3.5 w-full overflow-visible">
        <line x1="0" y1="7" x2="100%" y2="7" className="stroke-border" />
        <circle cx={`${pct}%`} cy="7" r="4" fill={CHART_SERIES[1]} className="stroke-card" strokeWidth="1.5" />
      </svg>
    </span>
  );
}

export function CompetidoresRanking({
  ordenados,
  tabla,
  metrica,
  totalEmpresas,
  search,
  sortKey,
  sortDir,
  onSort,
  abierta,
  rival,
  vigiladas,
  onAbrir,
  onComparar,
  isLoading,
}: {
  /** Lo que queda tras la búsqueda, por la medida activa. */
  ordenados: Competitor[];
  /** Lo mismo, con el orden de columna de la tabla completa. */
  tabla: Competitor[];
  metrica: Metrica;
  totalEmpresas: number | null;
  search: string;
  sortKey: SortKey;
  sortDir: "asc" | "desc";
  onSort: (key: SortKey) => void;
  abierta: string | null;
  rival: string | null;
  vigiladas: ReadonlySet<number>;
  onAbrir: (nombre: string) => void;
  onComparar: (nombre: string) => void;
  isLoading: boolean;
}) {
  const [vista, setVista] = useState<VistaRanking>("graficos");
  const [todas, setTodas] = useState(false);

  const visibles = todas ? ordenados : ordenados.slice(0, FILAS_RANKING);
  const escalas = escalasRanking(visibles);
  const ordenTxt = metrica === "importe" ? "importe" : "adjudicaciones";
  const enPantalla = vista === "tabla" ? tabla.length : visibles.length;

  return (
    <Panel>
      <PanelTitle
        // En el móvil el conmutador no cabe junto al título: baja de línea.
        className="max-sm:flex-wrap"
        title="Ranking de competidores"
        hint={
          vista === "graficos"
            ? `ordenado por ${ordenTxt} · pulsa una empresa para abrir su perfil`
            : "las doce columnas · pulsa una cabecera para ordenar"
        }
        actions={
          <>
            {search.trim() && (
              <Badge variant="neutral" size="sm">
                Filtrado
              </Badge>
            )}
            <Segmented value={vista} onChange={setVista} options={OPCIONES_VISTA} aria-label="Forma de la lista" size="xs" />
          </>
        }
      />
      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : ordenados.length === 0 ? (
        <PanelEmpty
          title={search ? "Ningún competidor coincide con la búsqueda" : "Ningún competidor"}
          hint={
            search
              ? "Prueba con otro nombre o NIF."
              : "No hay adjudicaciones en el ámbito actual. Amplía las fechas o quita filtros."
          }
        />
      ) : (
        <>
          {vista === "tabla" ? (
            <CompetidoresTabla
              filas={tabla}
              sortKey={sortKey}
              sortDir={sortDir}
              onSort={onSort}
              abierta={abierta}
              rival={rival}
              vigiladas={vigiladas}
              onAbrir={onAbrir}
              onComparar={onComparar}
            />
          ) : (
            <Table>
              <caption className="sr-only">Ranking de competidores, por {ordenTxt}</caption>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10 text-right">N.º</TableHead>
                  <TableHead>Empresa</TableHead>
                  <TableHead className="w-[17%] whitespace-nowrap">Cuota del importe</TableHead>
                  <TableHead className="text-right">Adjud.</TableHead>
                  <TableHead className="text-right">Importe</TableHead>
                  <TableHead className="w-[15%] whitespace-nowrap">
                    Baja media
                    {escalas.baja != null && (
                      <span className="font-normal normal-case"> · de 0 a {formatPercent(escalas.baja, 0)}</span>
                    )}
                  </TableHead>
                  <TableHead className="w-[10%] whitespace-nowrap">Ofertas / exped.</TableHead>
                  <TableHead className="w-[12%] whitespace-nowrap">Sin competencia</TableHead>
                  <TableHead className="whitespace-nowrap text-right">Última adj.</TableHead>
                  <TableHead>
                    <span className="sr-only">Comparar</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibles.map((c, idx) => {
                  const esAbierta = c.nombre === abierta;
                  return (
                    <TableRow key={rowKey(c, idx)} className={cn(esAbierta && "bg-primary/10")}>
                      <TableCell
                        numeric
                        className={cn("font-semibold", esAbierta ? "text-primary" : "text-muted-foreground")}
                      >
                        {idx + 1}
                      </TableCell>
                      <TableCell>
                        <CompetidorNombre
                          competitor={c}
                          abierta={esAbierta}
                          vigilada={esVigilada(c, vigiladas)}
                          onAbrir={onAbrir}
                        />
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <BarraPct
                            pct={escalas.cuota ? (c.cuota / escalas.cuota) * 100 : 0}
                            color={CHART_SERIES[0]}
                            className="min-w-12 flex-1"
                          />
                          <span className="tf-tnum w-12 shrink-0 text-right font-semibold">{formatPercent(c.cuota)}</span>
                        </div>
                      </TableCell>
                      <TableCell numeric>{formatNumber(c.count)}</TableCell>
                      <TableCell numeric>{formatCurrency(c.importe)}</TableCell>
                      <TableCell>
                        {c.baja_media != null && escalas.baja != null ? (
                          <div className="flex items-center gap-2">
                            <PuntoEnEscala valor={c.baja_media} tope={escalas.baja} />
                            <span className="tf-tnum w-12 shrink-0 text-right">{formatPercent(c.baja_media)}</span>
                          </div>
                        ) : (
                          <span className="text-muted-foreground">sin baja publicada</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {c.ofertas_medias != null && escalas.ofertas ? (
                          <div className="flex items-center gap-2">
                            <BarraPct
                              pct={(c.ofertas_medias / escalas.ofertas) * 100}
                              color={CHART_SERIES[2]}
                              className="h-1.5 min-w-8 flex-1"
                            />
                            <span className="tf-tnum w-7 shrink-0 text-right">
                              {c.ofertas_medias.toFixed(1).replace(".", ",")}
                            </span>
                          </div>
                        ) : (
                          <span className="text-muted-foreground">{EMPTY}</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {/* Sin dato de ofertantes no hay porcentaje que dar: un
                            «0 %» se leería como «nunca gana sin competencia». */}
                        {c.pct_monopolio != null ? (
                          <div className="flex items-center gap-2">
                            <BarraPct pct={c.pct_monopolio} color={CHART_SERIES[4]} className="h-1.5 min-w-8 flex-1" />
                            <span className="tf-tnum w-11 shrink-0 text-right">{formatPercent(c.pct_monopolio, 0)}</span>
                          </div>
                        ) : (
                          <span className="text-muted-foreground">sin dato</span>
                        )}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right text-muted-foreground">
                        {c.ultima ? formatDate(c.ultima) : EMPTY}
                      </TableCell>
                      <TableCell className="text-right">
                        <BotonComparar
                          nombre={c.nombre}
                          comparando={c.nombre === rival}
                          deshabilitado={esAbierta}
                          onComparar={onComparar}
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-2.5">
            <p className="text-tf-meta text-muted-foreground">
              Mostrando {formatNumber(enPantalla)} de{" "}
              {formatNumber(totalEmpresas != null && totalEmpresas > 0 ? totalEmpresas : ordenados.length)} competidores
              {vista === "graficos" && ". Cada barra y cada punto van a escala del mayor de las filas visibles."}
            </p>
            {vista === "graficos" && ordenados.length > FILAS_RANKING && (
              <Button type="button" variant="outline" size="sm" onClick={() => setTodas((valor) => !valor)}>
                {todas ? `Ver solo los ${FILAS_RANKING} primeros` : `Ver los ${formatNumber(ordenados.length)}`}
              </Button>
            )}
          </div>
        </>
      )}
    </Panel>
  );
}
