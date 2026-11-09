"use client";

/**
 * Pestaña «Favoritos»: licitaciones marcadas una a una, no capturadas por una
 * regla de criterio.
 *
 * Tiene sus propias queries (`useWatchlistItems`) en vez de recibirlas de la
 * página porque solo se monta cuando la pestaña está activa: quien nunca abre
 * Favoritos no paga la petición.
 *
 * Cada fila lleva su nota personal (CU-03), que se lee bajo el título y se
 * edita en la propia fila: una nota que obliga a abrir otra pantalla no se
 * escribe.
 */

import * as React from "react";
import Link from "next/link";
import { EnlaceFicha } from "@/components/ficha/enlace-ficha";
import { NotebookPen, Trash2 } from "lucide-react";
import { PanelEmpty, PanelError } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { CompararBoton } from "@/components/pliego/comparacion-bandeja";
import { EtiquetaChips, EtiquetasEditor } from "@/components/etiquetas/etiquetas-objeto";
import { useEtiquetasDe } from "@/hooks/use-etiquetas";
import { useRemoveWatchlistItem, useWatchlistItems } from "@/hooks/use-watchlist-items";
import { formatCurrency, formatDate, truncate } from "@/lib/utils";
import { NotaFavorito } from "./nota-favorito";

export function FavoritosPanel() {
  const { data: items, isLoading, error, refetch } = useWatchlistItems();
  const lista = React.useRef<HTMLUListElement>(null);
  // La fila se va al instante (retirada optimista) y con ella el botón que
  // tenía el foco: sin esto el teclado caía en `body`. Pasa al «Quitar» que
  // ocupa su sitio, o al anterior si era el último.
  const quitar = (idExterno: string, indice: number) => {
    removeItem.mutate(idExterno);
    requestAnimationFrame(() => {
      const botones = lista.current?.querySelectorAll<HTMLElement>("[data-quitar-favorito]");
      if (!botones?.length) return;
      botones[Math.min(indice, botones.length - 1)]?.focus();
    });
  };
  const removeItem = useRemoveWatchlistItem();
  // Una nota abierta a la vez: dos editores abiertos son dos borradores que
  // compiten por el mismo foco.
  const [editando, setEditando] = React.useState<string | null>(null);
  const botonesNota = React.useRef(new Map<string, HTMLButtonElement>());
  // F1.6 — el favorito se etiqueta por su `id_externo`; una sola petición
  // para toda la lista.
  const etiquetas =
    useEtiquetasDe(
      "favorito",
      (items ?? []).map((item) => item.id_externo),
    ).data ?? {};

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-14 w-full rounded-md" />
        ))}
      </div>
    );
  }

  // La consulta es silenciosa (también la usa «Seguir» en otras pantallas):
  // el fallo se pinta aquí. Sin esto caía en «No tienes favoritos», un vacío
  // falso que invitaba a volver a marcarlos.
  if (error) {
    return (
      <PanelError
        title="No se pudieron cargar tus favoritos"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  }

  if (!items || items.length === 0) {
    return (
      // Dice dónde está la estrella y lleva hasta ella (C7.3).
      <PanelEmpty
        title="No tienes licitaciones marcadas como favoritas"
        hint={
          <>
            Pulsa la estrella de una fila en{" "}
            <Link href="/detalle" className="text-primary font-medium hover:underline">
              Detalle
            </Link>{" "}
            (o la tecla S sobre la fila activa) y la licitación aparecerá aquí.
          </>
        }
      />
    );
  }

  return (
    <ul ref={lista} className="divide-divider border-divider bg-card divide-y rounded-xl border">
      {items.map((item, indice) => (
        <li key={item.id_externo} className="flex flex-col gap-2 px-4 py-2.5 sm:flex-row sm:items-center sm:gap-3">
          <div className="min-w-0 flex-1">
            <EnlaceFicha
              idExterno={item.id_externo}
              className="text-tf-body line-clamp-1 font-medium hover:underline"
            >
              {truncate(item.titulo ?? item.id_externo, 100)}
            </EnlaceFicha>
            <EtiquetaChips etiquetas={etiquetas[item.id_externo]} className="mt-1" />
            <NotaFavorito
              idExterno={item.id_externo}
              nota={item.nota}
              titulo={truncate(item.titulo ?? item.id_externo, 60)}
              editando={editando === item.id_externo}
              onTerminar={() => {
                setEditando(null);
                // Al cerrar el editor el foco vuelve al botón que lo abrió, en
                // vez de perderse en el documento.
                botonesNota.current.get(item.id_externo)?.focus();
              }}
            />
          </div>
          <EtiquetasEditor
            objetoTipo="favorito"
            objetoId={item.id_externo}
            aplicadas={etiquetas[item.id_externo]}
            descripcion={truncate(item.titulo ?? item.id_externo, 60)}
          />
          {item.importe != null && (
            <span className="tf-tnum text-tf-meta shrink-0 font-medium">{formatCurrency(item.importe)}</span>
          )}
          {item.estado && (
            <Badge size="sm" variant="outline" className="shrink-0">
              {item.estado}
            </Badge>
          )}
          {item.fecha_publicacion && (
            <span className="tf-tnum text-tf-meta text-muted-foreground shrink-0">
              {formatDate(item.fecha_publicacion)}
            </span>
          )}
          <CompararBoton id={item.id_externo} titulo={item.titulo} />
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                className="shrink-0"
                ref={(boton) => {
                  if (boton) botonesNota.current.set(item.id_externo, boton);
                  else botonesNota.current.delete(item.id_externo);
                }}
                aria-label={item.nota ? "Editar la nota" : "Añadir una nota"}
                aria-expanded={editando === item.id_externo}
                onClick={() => setEditando((actual) => (actual === item.id_externo ? null : item.id_externo))}
              >
                <NotebookPen aria-hidden="true" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{item.nota ? "Editar la nota" : "Añadir una nota"}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                className="text-destructive shrink-0"
                // Con el expediente en el nombre: en la lista de botones del
                // lector de pantalla, veinte «Quitar de favoritos» no se distinguen.
                aria-label={`Quitar de favoritos: ${item.titulo ?? item.id_externo}`}
                data-quitar-favorito
                onClick={() => quitar(item.id_externo, indice)}
              >
                <Trash2 aria-hidden="true" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Quitar de favoritos</TooltipContent>
          </Tooltip>
        </li>
      ))}
    </ul>
  );
}
