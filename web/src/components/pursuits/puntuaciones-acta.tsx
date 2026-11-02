"use client";

/**
 * Las puntuaciones que el acta de la mesa da a cada licitador, por lote, y los
 * puntos que separan a la empresa de la ganadora.
 *
 * Es el post-mortem que antes exigía abrir el PDF del acta y buscar la tabla:
 * «perdimos» no dice por cuánto ni en qué criterio. Todo lo que se pinta sale
 * de la API —filas, totales, ganadora, fila propia y diferencia—; aquí solo se
 * elige cómo leerlo. Cada cifra de la diferencia abre su página del acta en el
 * mismo visor que las citas de la ficha, porque una diferencia sin la página
 * de la que sale es una cifra que hay que creerse.
 *
 * La fila propia la propone la API por el nombre y la confirma una persona: la
 * tarjeta pregunta, no afirma. Confirmada, deja de ofrecer cambiarla.
 */
import { Fragment, useState } from "react";
import { PaginaPliegoDialog } from "@/components/pliego/pagina-pliego-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Pursuit } from "@/hooks/use-pursuits";
import type { EvidenceRef, Schemas } from "@/lib/api-types";
import type { MotivoPerdida } from "@/lib/motivos-perdida";
import { cn, formatNumber } from "@/lib/utils";

export type Puntuaciones = Schemas["PuntuacionesActa"];
export type FilaActaRef = Schemas["FilaActaRef"];
type Lote = Schemas["PuntuacionesLote"];
type Fila = Schemas["FilaPuntuacion"];
type Diferencia = Schemas["DiferenciaCriterio"];

/** Los estados sin tabla, con las palabras del spec §6.5. */
const TEXTO_ESTADO: Record<Exclude<Puntuaciones["estado"], "ok">, string> = {
  pendiente: "Leyendo el acta de la mesa",
  sin_acta: "PLACSP no publicó acta de mesa para este expediente",
  sin_tabla: "El acta no trae puntuaciones por licitador",
  error: "No se pudo leer el acta; se reintenta en la próxima pasada",
};

/**
 * El motivo de pérdida que proponen los puntos del acta, o `null`.
 *
 * Sale del lote que contiene la fila propia (confirmada o propuesta). El lote de
 * la oportunidad no se compara aquí: la API ya acota `lotes` al suyo cuando el
 * acta lo nombra, y el número de la oportunidad llega crudo mientras el del acta
 * llega normalizado. Si la fila propia está en varios lotes y sus motivos no
 * coinciden, ninguno: proponer el de un lote sería proponer el de otro contrato.
 */
export function motivoSugeridoDe(pursuit: Pursuit): MotivoPerdida | null {
  const lotes = pursuit.adjudicacion?.puntuaciones?.lotes ?? [];
  const motivos = new Set(
    lotes.flatMap((lote) => (lote.fila_propia != null && lote.motivo_sugerido ? [lote.motivo_sugerido] : [])),
  );
  return motivos.size === 1 ? [...motivos][0] : null;
}

/** «−18,5», «+2», «0»: el menos tipográfico, no el guion. */
function conSigno(valor: number): string {
  const cifra = formatNumber(Math.abs(valor));
  if (valor < 0) return `−${cifra}`;
  if (valor > 0) return `+${cifra}`;
  return cifra;
}

/** «Precio −18,5 de 65», o «Total −20,5» (criterio `null`). */
function textoDiferencia(diferencia: Diferencia): string {
  const nombre = diferencia.criterio ?? "Total";
  const sobre = diferencia.maximo != null ? ` de ${formatNumber(diferencia.maximo)}` : "";
  return `${nombre} ${conSigno(diferencia.diferencia)}${sobre}`;
}

/**
 * Las columnas de criterio, en el orden en que el acta los da. Cada fila trae
 * los suyos, y una excluida puede no traer ninguno: la cabecera es la unión.
 */
function columnasDe(filas: Fila[]): { nombre: string; maximo: number | null }[] {
  const columnas = new Map<string, number | null>();
  for (const fila of filas) {
    for (const criterio of fila.criterios) {
      if (columnas.get(criterio.nombre) == null) columnas.set(criterio.nombre, criterio.maximo);
    }
  }
  return [...columnas].map(([nombre, maximo]) => ({ nombre, maximo }));
}

function TablaLote({
  lote,
  confirmando,
  onConfirmarFila,
  onVerPagina,
}: {
  lote: Lote;
  confirmando: boolean;
  onConfirmarFila: (fila: FilaActaRef) => void;
  onVerPagina: (cita: EvidenceRef) => void;
}) {
  const columnas = columnasDe(lote.filas);
  const preguntar = !lote.fila_propia_confirmada;
  // Sin adjudicatario publicado que case con una fila, la de más puntos no es
  // «la ganadora»: es lo único que se sabe, y se dice así.
  const ganadora = lote.ganadora_es_mayor_puntuacion ? "la de mayor puntuación" : "la ganadora";
  const confirmar = (fila: Fila) =>
    onConfirmarFila({ lote_numero: lote.lote_numero, licitador_normalizado: fila.licitador_normalizado });

  return (
    <div>
      {/* `Table` ya va dentro de un contenedor con scroll propio: la tabla se
          desplaza en su caja y la página no gana scroll lateral en móvil. */}
      <Table>
        <TableCaption className="caption-top mt-0 mb-1.5 text-left font-medium text-foreground">
          Puntuaciones del acta de la mesa{lote.lote_numero ? ` · Lote ${lote.lote_numero}` : ""}
        </TableCaption>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead scope="col">Licitador</TableHead>
            {columnas.map((columna, indice) => (
              <TableHead key={`${indice}-${columna.nombre}`} scope="col" className="h-auto py-1 text-right">
                {columna.nombre}
                {columna.maximo != null && (
                  <>
                    {" "}
                    <span className="block font-normal normal-case tracking-normal">
                      sobre {formatNumber(columna.maximo)}
                    </span>
                  </>
                )}
              </TableHead>
            ))}
            <TableHead scope="col" className="text-right">
              Total
            </TableHead>
            {preguntar && (
              <TableHead scope="col">
                <span className="sr-only">Tu empresa</span>
              </TableHead>
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {lote.filas.map((fila, indice) => {
            const esGanadora = indice === lote.fila_ganadora;
            const esPropia = indice === lote.fila_propia;
            const puntos = new Map(fila.criterios.map((criterio) => [criterio.nombre, criterio.puntos]));
            return (
              <TableRow
                key={fila.licitador_normalizado}
                // El tinte acompaña al rótulo «Tu empresa», nunca va solo.
                className={cn(
                  esPropia && lote.fila_propia_confirmada && "bg-primary-selected hover:bg-primary-selected",
                  fila.excluida && "text-muted-foreground",
                )}
              >
                <TableCell className="min-w-40">
                  <span className={cn(esGanadora && "font-semibold")}>{fila.licitador}</span>
                  {(esGanadora || (esPropia && lote.fila_propia_confirmada) || fila.excluida) && (
                    <span className="ml-1.5 inline-flex flex-wrap gap-1 align-middle">
                      {esGanadora && (
                        <Badge size="sm" variant="outline">
                          {lote.ganadora_es_mayor_puntuacion ? "Mayor puntuación" : "Ganadora"}
                        </Badge>
                      )}
                      {esPropia && lote.fila_propia_confirmada && (
                        <Badge size="sm" variant="info">
                          Tu empresa
                        </Badge>
                      )}
                      {fila.excluida && (
                        <Badge size="sm" variant="neutral">
                          Excluida
                        </Badge>
                      )}
                    </span>
                  )}
                </TableCell>
                {columnas.map((columna, indiceColumna) => (
                  <TableCell key={`${indiceColumna}-${columna.nombre}`} numeric className="whitespace-nowrap">
                    {formatNumber(puntos.get(columna.nombre))}
                  </TableCell>
                ))}
                <TableCell numeric className="whitespace-nowrap font-semibold">
                  {formatNumber(fila.total)}
                </TableCell>
                {preguntar && (
                  <TableCell className="whitespace-nowrap text-right">
                    {esPropia ? (
                      <span className="inline-flex items-center gap-2">
                        <span className="text-tf-meta text-muted-foreground">¿Es esta tu empresa?</span>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={confirmando}
                          onClick={() => confirmar(fila)}
                          aria-label={`Confirmar que ${fila.licitador} es tu empresa`}
                        >
                          Confirmar
                        </Button>
                      </span>
                    ) : (
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={confirmando}
                        onClick={() => confirmar(fila)}
                        // Una por fila: el nombre accesible dice de cuál, y
                        // empieza por el texto visible (WCAG 2.5.3).
                        aria-label={`Esta es mi empresa: ${fila.licitador}`}
                      >
                        Esta es mi empresa
                      </Button>
                    )}
                  </TableCell>
                )}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      {lote.diferencia.length > 0 ? (
        <p className="mt-1.5 text-tf-meta">
          <span className="text-muted-foreground">Frente a {ganadora}: </span>
          {lote.diferencia.map((diferencia, indice) => {
            const texto = textoDiferencia(diferencia);
            const { documento_id, pagina } = diferencia;
            return (
              <Fragment key={`${indice}-${diferencia.criterio ?? "total"}`}>
                {indice > 0 && " · "}
                {documento_id != null && pagina != null ? (
                  <Button
                    variant="link"
                    size="sm"
                    // `inline` y `whitespace-normal`: el párrafo va fuera del
                    // contenedor con scroll de la tabla, y un criterio largo en
                    // una caja `inline-flex nowrap` empujaría la página en móvil.
                    className="inline h-auto whitespace-normal px-0 text-left align-baseline font-semibold md:h-auto"
                    aria-label={`${texto}, página ${pagina} del acta`}
                    onClick={() =>
                      onVerPagina({ documento_id, page_number: pagina, quote: "", ocr: false })
                    }
                  >
                    {texto}
                  </Button>
                ) : (
                  <span className="font-semibold">{texto}</span>
                )}
              </Fragment>
            );
          })}
        </p>
      ) : lote.fila_propia == null && lote.fila_ganadora != null ? (
        <p className="mt-1.5 text-tf-meta text-muted-foreground">
          Marca tu empresa para ver qué puntos te separan de {ganadora}.
        </p>
      ) : null}
    </div>
  );
}

export function PuntuacionesActa({
  pursuit,
  puntuaciones,
  onConfirmarFila,
  confirmando = false,
}: {
  pursuit: Pursuit;
  puntuaciones: Puntuaciones;
  onConfirmarFila: (fila: FilaActaRef) => void;
  confirmando?: boolean;
}) {
  const [paginaAbierta, setPaginaAbierta] = useState<EvidenceRef | null>(null);

  // `ok` sin lotes no debería llegar; si llega, es un acta sin tabla que leer.
  if (puntuaciones.estado !== "ok" || puntuaciones.lotes.length === 0) {
    const estado = puntuaciones.estado === "ok" ? "sin_tabla" : puntuaciones.estado;
    return <p className="text-tf-meta text-muted-foreground">{TEXTO_ESTADO[estado]}</p>;
  }

  return (
    <div className="space-y-4">
      {puntuaciones.lotes.map((lote) => (
        <TablaLote
          key={lote.lote_numero ?? "expediente"}
          lote={lote}
          confirmando={confirmando}
          onConfirmarFila={onConfirmarFila}
          onVerPagina={setPaginaAbierta}
        />
      ))}
      {/* El visor de las citas de la ficha, montado solo con una página abierta. */}
      {paginaAbierta && (
        <PaginaPliegoDialog
          licitacionId={pursuit.licitacion_id}
          cita={paginaAbierta}
          nombreDocumento="Acta de la mesa"
          onClose={() => setPaginaAbierta(null)}
        />
      )}
    </div>
  );
}
