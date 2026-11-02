"use client";

/**
 * La ficha de una licitación en un panel lateral, encima de cualquier pantalla
 * de la consola (ver `enlace-ficha.tsx`).
 *
 * **No es modal**: sin velo y sin cerrar al pulsar fuera, para que la lista de
 * debajo siga viva y otro clic cambie la ficha en vez de cerrarla. Se cierra
 * con Esc, con la X o navegando atrás. Es el mismo `DetailInspector` que el de
 * `/detalle`, así que no hay dos fichas que puedan divergir; «Ficha completa»
 * lleva a `/detalle` con la tabla.
 *
 * `GET /licitaciones/{id}` no trae el score, y aquí no hay tabla que lo
 * aporte: la ficha lo omite, como con un permalink de `/detalle` que no está en
 * la página.
 */
import * as React from "react";
import { useRouter } from "next/navigation";
import { DetailInspector } from "@/components/detail-inspector";
import { PanelError } from "@/components/console/panel";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useLicitacion } from "@/hooks/use-licitacion";
import type { LicitacionDetail } from "@/lib/licitacion-detail";
import { rutaFicha, useFichaFlotante } from "./enlace-ficha";

export function FichaFlotante() {
  const [abierta, setVer] = useFichaFlotante();
  // La última abierta sigue pintada mientras el panel sale al cerrarse.
  const [idExterno, setIdExterno] = React.useState(abierta);
  if (abierta && abierta !== idExterno) setIdExterno(abierta);
  const router = useRouter();
  // El mismo GET y la misma clave que /detalle, que lo tipa con `lib/licitacion-detail`
  // (campos opcionales como `null`): de ahí el `as` del inspector.
  const { data, error, refetch } = useLicitacion(idExterno);
  const cerrar = () => void setVer(null, { history: "replace" });

  return (
    <Sheet open={Boolean(abierta)} modal={false} onOpenChange={(abierto) => !abierto && cerrar()}>
      <SheetContent
        side="right"
        // Mismo marco que el `Sheet` de /detalle: el inspector trae su ritmo
        // (`p-0`) y su propio «Cerrar · Esc» (`[&>button]:hidden`).
        className="flex w-[min(36rem,94vw)] flex-col gap-0 p-0 sm:max-w-none [&>button]:hidden"
        aria-describedby={undefined}
        onInteractOutside={(evento) => evento.preventDefault()}
      >
        <SheetTitle className="sr-only">Ficha de la licitación</SheetTitle>
        {data && data.id_externo === idExterno ? (
          // Una ficha por expediente: el scroll y la pestaña no pasan a la siguiente.
          <DetailInspector
            key={data.id_externo}
            licitacion={data as LicitacionDetail}
            onClose={cerrar}
            onExpandir={() => router.push(`${rutaFicha(data.id_externo)}&ficha=completa`)}
          />
        ) : error ? (
          <PanelError
            title="No se pudo abrir la ficha"
            error={error}
            onRetry={() => void refetch()}
            className="m-4"
          />
        ) : (
          <div className="flex flex-col gap-3 p-4" aria-busy="true">
            <Skeleton className="h-5 w-24" />
            <Skeleton className="h-7 w-full" />
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="mt-2 h-24 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
