"use client";

/**
 * La ficha de una licitación junto a cualquier pantalla de la consola (ver
 * `enlace-ficha.tsx`).
 *
 * **Desde `xl` va anclada**: es una columna del marco (`ConsoleFrame`, ranura
 * `lateral`) y la pantalla se estrecha para dejarle sitio, igual que el
 * inspector de `/detalle` y el del Radar. Por debajo de `xl` no caben las dos
 * cosas y entra como panel lateral encima.
 *
 * **No es modal** en ningún caso: sin velo y sin cerrar al pulsar fuera, para
 * que la lista siga viva y otro clic cambie la ficha en vez de cerrarla. Se
 * cierra con Esc, con la X o navegando atrás. Es el mismo `DetailInspector` que
 * el de `/detalle`, así que no hay dos fichas que puedan divergir; «Ficha
 * completa» lleva a `/detalle` con la tabla.
 *
 * `GET /licitaciones/{id}` no trae el score, y aquí no hay tabla que lo
 * aporte: la ficha lo omite, como con un permalink de `/detalle` que no está en
 * la página.
 */
import * as React from "react";
import { useRouter } from "next/navigation";
import { useModoInspector } from "@/app/(dashboard)/radar/_hooks/use-media-query";
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
  const anclada = useModoInspector() === "anclado";
  // El mismo GET y la misma clave que /detalle, que lo tipa con `lib/licitacion-detail`
  // (campos opcionales como `null`): de ahí el `as` del inspector.
  const { data, error, refetch } = useLicitacion(idExterno);
  const cerrar = () => void setVer(null, { history: "replace" });

  // El `Sheet` trae su Esc; la columna anclada no, y lo mismo vale para el
  // teclado de /detalle: se ignora dentro de un campo de texto, y lo que ya
  // atendió otra capa (la paleta, un menú) llega con `defaultPrevented`.
  React.useEffect(() => {
    if (!anclada || !abierta) return;
    const alPulsar = (evento: KeyboardEvent) => {
      const destino = evento.target as HTMLElement | null;
      const escribiendo = destino?.tagName === "INPUT" || destino?.tagName === "TEXTAREA" || destino?.isContentEditable;
      if (evento.key !== "Escape" || evento.defaultPrevented || escribiendo) return;
      void setVer(null, { history: "replace" });
    };
    window.addEventListener("keydown", alPulsar);
    return () => window.removeEventListener("keydown", alPulsar);
  }, [anclada, abierta, setVer]);

  const cuerpo =
    data && data.id_externo === idExterno ? (
      // Una ficha por expediente: el scroll y la pestaña no pasan a la siguiente.
      <DetailInspector
        key={data.id_externo}
        licitacion={data as LicitacionDetail}
        onClose={cerrar}
        onExpandir={() => router.push(`${rutaFicha(data.id_externo)}&ficha=completa`)}
      />
    ) : error ? (
      <PanelError title="No se pudo abrir la ficha" error={error} onRetry={() => void refetch()} className="m-4" />
    ) : (
      <div className="flex flex-col gap-3 p-4" aria-busy="true">
        <Skeleton className="h-5 w-24" />
        <Skeleton className="h-7 w-full" />
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="mt-2 h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );

  if (anclada) {
    // Sin animación de salida, como el inspector de /detalle: desaparece con `?ver=`.
    return abierta ? (
      <div className="flex w-[clamp(30rem,40vw,46rem)] flex-none flex-col border-l border-divider bg-card">{cuerpo}</div>
    ) : null;
  }

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
        {cuerpo}
      </SheetContent>
    </Sheet>
  );
}
