"use client";

/**
 * Avisa antes de salir de una pantalla con cambios sin guardar.
 *
 * Dos salidas distintas, dos mecanismos:
 *
 * - **Cerrar o recargar la pestaña** (o ir a otro sitio): `beforeunload`, que
 *   es lo único que el navegador deja interceptar ahí, con su propio diálogo.
 * - **Un enlace de la consola** (el rail, una cabecera, un «ir a»): Next no
 *   recarga nada, así que `beforeunload` no salta y la pantalla se desmontaba
 *   con lo tecleado dentro. Se escucha el clic en fase de captura —antes de que
 *   llegue al `Link`, que no navega si el evento ya viene cancelado— y se
 *   pregunta con un diálogo propio.
 *
 * No cubre lo que navega sin enlace: la paleta de comandos, el botón de atrás
 * o el cambio de organización activa. Mientras `activo` sea falso no escucha
 * nada.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";

/** Destino dentro de la consola al que apunta el clic, o `null` si no hay que preguntar. */
function destinoInterno(evento: MouseEvent): string | null {
  if (evento.defaultPrevented || evento.button !== 0) return null;
  // Con una tecla modificadora el enlace se abre en otra pestaña: esta se queda.
  if (evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.altKey) return null;
  const origen = evento.target instanceof Element ? evento.target.closest("a[href]") : null;
  if (!(origen instanceof HTMLAnchorElement)) return null;
  if ((origen.target && origen.target !== "_self") || origen.hasAttribute("download")) return null;
  const url = new URL(origen.href, window.location.href);
  // Fuera de la consola hay recarga, y de esa ya avisa `beforeunload`.
  if (url.origin !== window.location.origin) return null;
  // La misma pantalla (otra vista, un ancla) no desmonta el formulario.
  if (url.pathname === window.location.pathname) return null;
  return `${url.pathname}${url.search}${url.hash}`;
}

export function AvisoCambiosSinGuardar({ activo }: { activo: boolean }) {
  const router = useRouter();
  const [destino, setDestino] = useState<string | null>(null);

  useEffect(() => {
    if (!activo) return;
    const alCerrar = (evento: BeforeUnloadEvent) => evento.preventDefault();
    const alPulsar = (evento: MouseEvent) => {
      const interno = destinoInterno(evento);
      if (interno == null) return;
      evento.preventDefault();
      setDestino(interno);
    };
    window.addEventListener("beforeunload", alCerrar);
    document.addEventListener("click", alPulsar, true);
    return () => {
      window.removeEventListener("beforeunload", alCerrar);
      document.removeEventListener("click", alPulsar, true);
    };
  }, [activo]);

  if (destino == null) return null;

  return (
    <Dialog open onOpenChange={(abierto) => (abierto ? undefined : setDestino(null))}>
      <DialogContent className="w-[420px] max-w-[calc(100vw-2rem)] p-5">
        <DialogTitle>Tienes cambios sin guardar</DialogTitle>
        <DialogDescription className="mt-1 mb-4">
          Si sales ahora se pierden. Puedes quedarte y guardarlos antes.
        </DialogDescription>
        <div className="flex items-center justify-end gap-2">
          <Button variant="outline" size="sm" onClick={() => setDestino(null)}>
            Seguir editando
          </Button>
          <Button
            size="sm"
            onClick={() => {
              setDestino(null);
              router.push(destino);
            }}
          >
            Salir sin guardar
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
