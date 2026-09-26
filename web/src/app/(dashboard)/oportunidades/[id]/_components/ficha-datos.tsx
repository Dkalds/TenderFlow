"use client";

import type * as React from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { iniciales, plazoVisual } from "@/components/pursuits/pursuit-presenters";
import { useLicitacion } from "@/hooks/use-licitacion";
import { esTerminal, type Pursuit } from "@/hooks/use-pursuits";
import { textoAdjudicacion } from "@/lib/adjudicacion-prevista";
import { cn, formatCompactCurrency, formatDate } from "@/lib/utils";
import { BotonEditar, EditorOferta, EditorResponsable } from "./ficha-datos-editores";

/** Los dos datos de la rejilla que se editan en su propia celda. */
export type CampoDeDatos = "oferta" | "responsable";

/**
 * Los datos que sostienen la decisión, en una rejilla de celdas pegadas.
 *
 * Los cuatro del diseño —oferta, plazo, importe y responsable— más la
 * adjudicación prevista. El órgano ya no ocupa celda: lo dice el subtítulo de
 * la cabecera, y su sitio lo ocupa el importe de licitación, la primera cifra
 * que se mira para decidir y que la ficha solo enseñaba en «Expediente». Ninguna
 * cifra se calcula aquí: el pursuit y el expediente las traen hechas.
 *
 * La oferta y el responsable se editan en su celda. Son los dos huecos que más
 * piden los pasos de salida, y antes se rellenaban al final de «Todos los
 * campos», a un scroll de distancia de donde se veía que faltaban. `editando`
 * lo controla la ficha, que abre la celda también desde el paso pendiente.
 */
export function FichaDatos({
  pursuit,
  editando = null,
  onEditar,
}: {
  pursuit: Pursuit;
  editando?: CampoDeDatos | null;
  onEditar?: (campo: CampoDeDatos | null) => void;
}) {
  const cerrada = esTerminal(pursuit.status);
  const plazo = plazoVisual(pursuit.tender_deadline);
  const sinImporte = pursuit.offer_price_eur == null;
  const adjudicacion = textoAdjudicacion(pursuit.expected_award);

  return (
    <div className="flex flex-col gap-1.5">
      <dl
        aria-label="Datos de la oportunidad"
        className="border-border/60 bg-border/60 grid grid-cols-2 gap-px overflow-hidden rounded-xl border"
      >
        <Celda
          etiqueta="Oferta prevista"
          accion={
            onEditar && editando !== "oferta" ? (
              <BotonEditar
                etiqueta={sinImporte ? "Anotar la oferta prevista" : "Editar la oferta prevista"}
                onClick={() => onEditar("oferta")}
              />
            ) : null
          }
        >
          {editando === "oferta" && onEditar ? (
            <EditorOferta pursuit={pursuit} onCerrar={() => onEditar(null)} />
          ) : (
            <span
              className={cn(
                "tf-tnum font-mono text-tf-lede leading-none font-semibold",
                sinImporte && !cerrada && "text-[hsl(var(--warning))]",
              )}
            >
              {sinImporte ? "Sin importe" : formatCompactCurrency(pursuit.offer_price_eur)}
            </span>
          )}
        </Celda>

        <Celda etiqueta="Plazo de presentación">
          {plazo ? (
            <span className="flex items-baseline gap-1.5">
              <span
                className={cn(
                  "tf-tnum font-mono text-tf-lede leading-none font-semibold",
                  plazo.clases.texto,
                )}
              >
                {plazo.dias < 0 ? "Vencido" : `${plazo.dias} d`}
              </span>
              <span className="text-muted-foreground text-tf-micro">
                {formatDate(pursuit.tender_deadline)}
              </span>
            </span>
          ) : (
            <span className="text-tf-body font-medium">Sin fecha límite</span>
          )}
        </Celda>

        <ImporteLicitacion pursuit={pursuit} />

        <Celda
          etiqueta="Responsable"
          accion={
            onEditar && editando !== "responsable" ? (
              <BotonEditar
                etiqueta={pursuit.responsible_name ? "Cambiar el responsable" : "Asignar un responsable"}
                onClick={() => onEditar("responsable")}
              />
            ) : null
          }
        >
          {editando === "responsable" && onEditar ? (
            <EditorResponsable pursuit={pursuit} onCerrar={() => onEditar(null)} />
          ) : (
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className={cn(
                  "grid h-5 w-5 flex-none place-items-center rounded-full font-mono text-tf-micro font-semibold",
                  pursuit.responsible_name
                    ? "bg-primary/14 text-primary"
                    : "border-border/60 text-muted-foreground border border-dashed",
                )}
              >
                {iniciales(pursuit.responsible_name)}
              </span>
              <span className="min-w-0 truncate text-tf-body font-medium">
                {pursuit.responsible_name ?? "Sin asignar"}
              </span>
            </span>
          )}
        </Celda>

        {/* A ancho completo: su base es una frase entera, y en media celda
            la estiraba hasta siete líneas y descuadraba la rejilla. */}
        {cerrada ? (
          <Celda etiqueta="Importe adjudicado" ancha>
            <span className="tf-tnum font-mono text-tf-body font-semibold">
              {formatCompactCurrency(pursuit.awarded_amount_eur)}
            </span>
          </Celda>
        ) : (
          <Celda etiqueta="Adjudicación prevista" pie={adjudicacion.base} ancha>
            <span className="text-tf-body font-medium">
              {adjudicacion.valor}
              {adjudicacion.metodo === "estimacion" ? (
                <span className="border-border/70 bg-muted/60 text-muted-foreground ml-1.5 inline-flex items-center rounded-sm border px-1.5 align-middle text-tf-micro font-medium">
                  estimación
                </span>
              ) : null}
            </span>
          </Celda>
        )}
      </dl>
      <p className="text-muted-foreground px-1 text-tf-micro">
        Actualizada el {formatDate(pursuit.updated_at)}
      </p>
    </div>
  );
}

/**
 * El importe de lo que se licita: el del lote si la oportunidad es de un lote,
 * porque es sobre ese presupuesto sobre el que se puja (S3.1).
 *
 * Sale del expediente (`useLicitacion`), la misma consulta que la pestaña
 * «Expediente», así que abrirla después no pide nada más. `importe` es la base
 * sin IVA en lo ingerido desde `v113` y puede no serlo en lo anterior
 * (ADR-032): por eso la etiqueta no afirma «sin IVA».
 */
function ImporteLicitacion({ pursuit }: { pursuit: Pursuit }) {
  const { data: licitacion, isPending } = useLicitacion(pursuit.licitacion_id);
  const lote = pursuit.lote_numero
    ? licitacion?.lotes?.find((candidato) => candidato.numero === pursuit.lote_numero)
    : undefined;
  // Un lote que el pliego ya no publica no tiene importe propio que enseñar:
  // se dice que el que se ve es el del expediente, igual que los escenarios.
  const deLote = lote != null;
  const importe = deLote ? lote.importe : licitacion?.importe;
  const etiqueta = deLote
    ? `Importe del lote ${pursuit.lote_numero}`
    : pursuit.lote_numero
      ? "Importe del expediente"
      : "Importe de licitación";

  return (
    <Celda etiqueta={etiqueta}>
      {isPending ? (
        <Skeleton className="h-[15px] w-20 rounded" />
      ) : importe != null ? (
        <span className="tf-tnum font-mono text-tf-lede leading-none font-semibold">
          {formatCompactCurrency(importe)}
        </span>
      ) : (
        <span className="text-muted-foreground text-tf-body">Sin importe publicado</span>
      )}
    </Celda>
  );
}

function Celda({
  etiqueta,
  pie,
  accion,
  ancha = false,
  children,
}: {
  etiqueta: string;
  pie?: string;
  accion?: React.ReactNode;
  ancha?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("bg-card min-w-0 px-3.5 py-2.5", ancha && "col-span-2")}>
      {/* El botón de editar va dentro del `dt` y no en un envoltorio: un
          grupo de `dl` solo admite `dt` y `dd` como hijos. */}
      <dt className="mb-1.5 flex items-center justify-between gap-1">
        <span className="text-muted-foreground font-mono text-tf-micro font-semibold tracking-wider uppercase">
          {etiqueta}
        </span>
        {accion}
      </dt>
      <dd>{children}</dd>
      {pie ? <dd className="text-muted-foreground mt-0.5 text-tf-micro leading-[1.4]">{pie}</dd> : null}
    </div>
  );
}
