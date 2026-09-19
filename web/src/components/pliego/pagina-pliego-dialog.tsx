"use client";

import * as React from "react";
import { AlertTriangle, ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { usePaginaDocumento } from "@/hooks/use-pagina-documento";
import type { EvidenceRef } from "@/lib/api-types";
import { ApiError } from "@/lib/api-client";
import { registrarEvento } from "@/lib/analytics";
import { espacioActual } from "@/lib/espacio-actual";

/**
 * F2.5 — visor de página del pliego con la cita resaltada.
 *
 * Sin binario: es el texto extraído de la página (`documento_pages`), con el
 * fragmento marcado por los offsets que la API ya devuelve **relativos a esta
 * página**. El PDF real llega con el almacén de objetos (v2 S8.1); mientras,
 * el enlace al documento original da salida al portal de la fuente.
 */

/** Por qué no se marcó la cita, en palabras de quien la está leyendo. */
export const MOTIVOS_SIN_RESALTADO: Record<string, string> = {
  sin_offsets: "La cita no guarda su posición en el documento.",
  offsets_invertidos: "La posición guardada de la cita es incoherente.",
  offsets_fuera_de_rango: "La posición guardada de la cita no cae en esta página.",
};

/**
 * Parte el texto en antes / cita / después. `null` si los índices no sirven:
 * la página se pinta entera antes que marcar el trozo equivocado.
 */
export function trocearResaltado(
  texto: string,
  inicio: number | null | undefined,
  fin: number | null | undefined,
): { antes: string; cita: string; despues: string } | null {
  if (inicio == null || fin == null || inicio < 0 || fin <= inicio || fin > texto.length) {
    return null;
  }
  return { antes: texto.slice(0, inicio), cita: texto.slice(inicio, fin), despues: texto.slice(fin) };
}

export function PaginaPliegoDialog({
  licitacionId,
  cita,
  nombreDocumento,
  onClose,
}: {
  licitacionId: string;
  /** La cita a abrir; `null` = diálogo cerrado. */
  cita: EvidenceRef | null;
  nombreDocumento?: string | null;
  onClose: () => void;
}) {
  const [pagina, setPagina] = React.useState(cita?.page_number ?? 1);
  // Al abrir otra cita se vuelve a su página. Derivado durante el render, como
  // hace el inspector al cambiar de licitación, en vez de con un efecto.
  const [citaPrevia, setCitaPrevia] = React.useState(cita);
  if (citaPrevia !== cita) {
    setCitaPrevia(cita);
    if (cita) setPagina(cita.page_number);
  }

  // F2.5 — se abrió una cita. Una vez por cita abierta, no por página
  // recorrida: navegar dentro del documento es leer la misma evidencia. Va en
  // `espacio_abierto` con su propio origen porque abrir una cita no es una
  // navegación del rail ni del conmutador.
  React.useEffect(() => {
    if (cita == null) return;
    registrarEvento("espacio_abierto", {
      espacio: espacioActual(),
      origen: "cita",
      evidencia_abierta: "si",
    });
  }, [cita]);

  const enPaginaDeLaCita = cita != null && pagina === cita.page_number;
  const consulta = usePaginaDocumento(
    licitacionId,
    cita
      ? {
          documentoId: cita.documento_id,
          pagina,
          inicio: enPaginaDeLaCita ? cita.start_offset : null,
          fin: enPaginaDeLaCita ? cita.end_offset : null,
        }
      : null,
  );
  const data = consulta.data;
  const trozos = data && enPaginaDeLaCita
    ? trocearResaltado(data.texto, data.resaltado_inicio, data.resaltado_fin)
    : null;

  // El fragmento marcado se trae a la vista: en una página de 4.000 caracteres
  // la cita puede estar al final, y abrir el visor arriba obligaría a buscarla.
  const marca = React.useRef<HTMLElement>(null);
  React.useEffect(() => {
    marca.current?.scrollIntoView({ block: "center" });
  }, [trozos?.cita, data?.page_number]);

  const sinResaltado =
    enPaginaDeLaCita && data && !trozos
      ? (MOTIVOS_SIN_RESALTADO[data.resaltado_omitido ?? "sin_offsets"] ??
        "No se pudo situar la cita en esta página.")
      : null;
  const nombre = data?.filename ?? nombreDocumento ?? (cita ? `Documento ${cita.documento_id}` : "");
  const total = data?.total_paginas ?? null;
  const noExiste = consulta.error instanceof ApiError && consulta.error.status === 404;

  return (
    <Dialog open={cita != null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="mx-4 flex max-h-[90vh] w-full max-w-3xl flex-col gap-3">
        <div className="pr-8">
          <DialogTitle className="text-base">
            {nombre} · página {pagina}
            {total != null && ` de ${total}`}
          </DialogTitle>
          <DialogDescription className="mt-1 text-xs">
            Texto extraído de la página del pliego
            {trozos ? ", con la cita resaltada." : "."}
          </DialogDescription>
        </div>

        {sinResaltado && (
          <p
            role="status"
            className="flex gap-2 rounded-lg border border-warning/30 bg-warning/10 p-2.5 text-xs text-warning"
          >
            <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>{sinResaltado} Se muestra la página completa sin resaltar.</span>
          </p>
        )}

        <div
          // Sin `tabIndex`: jsx-a11y lo prohíbe en un elemento no interactivo,
          // y los navegadores actuales ya hacen enfocable con teclado una
          // región con scroll que no contiene nada enfocable.
          className="min-h-40 flex-1 overflow-y-auto rounded-lg border border-border/60 bg-background/60 p-3 text-sm leading-relaxed whitespace-pre-wrap"
        >
          {consulta.isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ) : noExiste ? (
            <p className="text-muted-foreground">No hay texto extraído para esta página.</p>
          ) : consulta.error ? (
            <p role="alert" className="text-destructive">
              No se pudo cargar la página. {(consulta.error as Error).message}
            </p>
          ) : data ? (
            trozos ? (
              <>
                {trozos.antes}
                <mark ref={marca} className="rounded-sm bg-primary/25 px-0.5 text-foreground">
                  {trozos.cita}
                </mark>
                {trozos.despues}
              </>
            ) : (
              data.texto || <span className="text-muted-foreground">Página sin texto.</span>
            )
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={pagina <= 1}
            onClick={() => setPagina((p) => Math.max(1, p - 1))}
          >
            <ChevronLeft aria-hidden="true" />
            Página anterior
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={total == null || pagina >= total}
            onClick={() => setPagina((p) => p + 1)}
          >
            Página siguiente
            <ChevronRight aria-hidden="true" />
          </Button>
          {!enPaginaDeLaCita && cita && (
            <Button size="sm" variant="ghost" onClick={() => setPagina(cita.page_number)}>
              Volver a la cita
            </Button>
          )}
          <div className="flex-1" />
          {data?.uri && (
            <a
              href={`${data.uri}#page=${pagina}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              Abrir el documento original
              <ExternalLink className="h-3 w-3" aria-hidden="true" />
            </a>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
