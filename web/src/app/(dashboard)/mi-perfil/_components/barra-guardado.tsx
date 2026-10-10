"use client";

/**
 * Las acciones del formulario del perfil, siempre a la vista mientras haya
 * algo que guardar.
 *
 * Con nueve bloques por encima, el botón de guardar quedaba varias pantallas
 * más abajo que el interruptor de «Compartir» que también guarda. Mientras hay
 * cambios la barra se pega al borde inferior y dice que los hay; sin ellos
 * vuelve a su sitio, al final del formulario.
 *
 * «Eliminar perfil» se confirma en dos pasos, como el resto de la consola:
 * antes borraba al primer clic, pegado a «Guardar».
 */

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function BarraGuardado({
  dirty,
  motivoBloqueo,
  guardando,
  onGuardar,
  onDescartar,
  puedeEliminar,
  eliminando,
  onEliminar,
}: {
  dirty: boolean;
  /** Por qué no se puede guardar lo que hay en pantalla, si es el caso. */
  motivoBloqueo?: string | null;
  guardando: boolean;
  onGuardar: () => void;
  onDescartar: () => void;
  /** Hay un perfil propio que borrar (uno heredado no es de quien lo ve). */
  puedeEliminar: boolean;
  eliminando: boolean;
  onEliminar: () => void;
}) {
  const [confirmando, setConfirmando] = useState(false);
  // Con cambios pendientes, borrar se llevaría también lo que no se ha guardado.
  const ofreceEliminar = puedeEliminar && !dirty;

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-2",
        dirty && "tf-glass-strong sticky bottom-3 z-10 rounded-xl border border-border/70 px-3.5 py-2.5 shadow-md",
      )}
    >
      {dirty ? (
        <p role="status" className={cn("text-tf-meta", motivoBloqueo ? "text-destructive" : "text-warning")}>
          {motivoBloqueo ?? "Cambios sin guardar"}
        </p>
      ) : (
        // Mientras se confirma el borrado la pregunta ocupa la fila: este
        // rótulo solo la partía en dos líneas.
        !confirmando && <p className="text-tf-meta text-muted-foreground">Sin cambios que guardar.</p>
      )}
      <div className="flex-1" />

      {ofreceEliminar &&
        (confirmando ? (
          <div role="group" aria-label="Confirmar eliminación del perfil" className="flex flex-wrap items-center gap-2">
            <span className="text-tf-meta text-muted-foreground">
              ¿Eliminar tu perfil? El Radar vuelve a los pesos globales.
            </span>
            <Button
              size="sm"
              variant="destructive"
              disabled={eliminando}
              onClick={() => {
                setConfirmando(false);
                onEliminar();
              }}
            >
              Sí, eliminar
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmando(false)}>
              Cancelar
            </Button>
          </div>
        ) : (
          <Button
            size="sm"
            variant="outline"
            disabled={eliminando}
            onClick={() => setConfirmando(true)}
            className="text-destructive hover:bg-destructive/5"
          >
            {eliminando ? "Eliminando…" : "Eliminar perfil"}
          </Button>
        ))}

      {dirty && (
        <Button size="sm" variant="ghost" onClick={onDescartar} disabled={guardando}>
          Descartar
        </Button>
      )}
      <Button size="sm" onClick={onGuardar} disabled={!dirty || guardando || motivoBloqueo != null}>
        {guardando ? "Guardando…" : "Guardar perfil"}
      </Button>
    </div>
  );
}
