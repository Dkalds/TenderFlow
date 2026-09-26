"use client";

import type { Pursuit } from "@/hooks/use-pursuits";
import { FichaDatos, type CampoDeDatos } from "./ficha-datos";
import { ProximaAccion } from "./proxima-accion";

/** Lo que se edita en su sitio, sin salir de la columna de datos. */
export type Editable = CampoDeDatos | "proxima";

/**
 * La columna de datos: lo que se consulta mientras se trabaja en la otra.
 *
 * Fija en `xl` (`sticky`): acababa a un tercio del Resumen y el resto de la
 * columna quedaba vacío justo cuando se bajaba a trabajar el pliego o el kit.
 * La acompañan las pestañas donde se trabaja la oferta —«Pliego» y «Precio»—,
 * para que la oferta prevista y el plazo sigan a la vista allí.
 *
 * Qué celda está en edición lo decide la ficha: la abre también el paso
 * pendiente del bloque de salida, que vive en la otra columna.
 */
export function ColumnaDatos({
  pursuit,
  editando,
  onEditar,
}: {
  pursuit: Pursuit;
  editando: Editable | null;
  onEditar: (campo: Editable | null) => void;
}) {
  return (
    <aside
      aria-label="Datos y próxima acción"
      // `top-4`: el mismo aire que el relleno del contenedor con scroll, así
      // que al fijarse no se mueve.
      className="flex flex-col gap-3.5 xl:sticky xl:top-4 xl:col-start-2 xl:row-span-2 xl:row-start-1 xl:self-start"
    >
      <FichaDatos
        pursuit={pursuit}
        editando={editando === "proxima" ? null : editando}
        onEditar={onEditar}
      />
      <ProximaAccion
        key={`${pursuit.id}:${pursuit.version}`}
        pursuit={pursuit}
        editando={editando === "proxima"}
        onEditar={(abierto) => onEditar(abierto ? "proxima" : null)}
      />
    </aside>
  );
}
