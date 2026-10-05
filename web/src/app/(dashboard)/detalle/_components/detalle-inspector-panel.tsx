"use client";

import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { DetailInspector } from "@/components/detail-inspector";
import type { LicitacionDetail } from "@/lib/licitacion-detail";
import type { ModoInspector } from "../../radar/_hooks/use-media-query";

/**
 * Dónde vive la ficha de la licitación, según el ancho.
 *
 * - **≥ xl — anclado.** El inspector escala con la pantalla en vez de quedarse
 *   en 428px fijos. Con ese ancho la ficha era la parte estrecha del plano: el
 *   título rompía en tres líneas, los diez campos vivían en dos columnas de
 *   200px y el chat de IA leía como una columna de móvil. El suelo de 28rem
 *   mantiene el panel usable en un portátil de 1280 y el techo de 42rem evita
 *   que en un monitor de 2560 la ficha se estire sin ganar nada.
 * - **md–xl — `Sheet`.** Aquí no caben tabla e inspector a la vez, pero el
 *   `?lic=` ya existía y no pintaba nada: abrir una fila era un clic sin
 *   respuesta. Ahora la ficha entra como panel lateral sobre la tabla y se
 *   cierra con Esc, con la X o navegando atrás.
 * - **< md — la ficha completa.** La tabla mide 1358 px y no deja sitio a un
 *   panel: abrir una fila (o un permalink) cambia la tabla por la ficha
 *   completa (`detalle-ficha-completa.tsx`), y este componente no se monta.
 *
 * En los tres casos la fuente es la misma `LicitacionDetail`: no hay dos
 * versiones de la ficha que puedan divergir.
 *
 * `onExpandir` abre la ficha completa, que sustituye a la tabla y a este
 * panel; por debajo de `md` es la única ficha (ver `use-ficha-completa`).
 */
export function DetalleInspectorPanel({
  modo,
  licitacion,
  onClose,
  onExpandir,
}: {
  modo: ModoInspector;
  licitacion: LicitacionDetail | null;
  onClose: () => void;
  onExpandir: () => void;
}) {
  if (!licitacion) return null;

  if (modo === "sheet") {
    return (
      <Sheet open onOpenChange={(abierto) => !abierto && onClose()}>
        <SheetContent
          side="right"
          // `p-0` porque el inspector trae su propio ritmo de márgenes, y
          // `[&>button]:hidden` esconde la X que el Sheet pone en `right-4
          // top-4`: la cabecera de la ficha ya tiene su propio «Cerrar · Esc».
          className="flex w-[min(32rem,94vw)] flex-col gap-0 p-0 sm:max-w-none [&>button]:hidden"
          aria-describedby={undefined}
        >
          <SheetTitle className="sr-only">Ficha de la licitación</SheetTitle>
          {/* Como en el Radar, una ficha por expediente: así el scroll y el
              «Preguntar» pendiente no pasan a la siguiente. */}
          <DetailInspector
            key={licitacion.id_externo}
            licitacion={licitacion}
            onClose={onClose}
            onExpandir={onExpandir}
          />
        </SheetContent>
      </Sheet>
    );
  }

  return (
    <div className="hidden w-[clamp(28rem,32vw,42rem)] flex-none xl:flex">
      <DetailInspector
        key={licitacion.id_externo}
        licitacion={licitacion}
        onClose={onClose}
        onExpandir={onExpandir}
      />
    </div>
  );
}
