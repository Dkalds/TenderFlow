"use client";

/**
 * Suscripción al calendario de compromisos desde la agenda.
 *
 * Lo que hace útil a un ICS es que el cliente de calendario lo refresque solo;
 * por eso lo que se ofrece primero es la URL de suscripción y no una descarga.
 * La nota de privacidad no es adorno: la URL lleva una firma personal y quien
 * la tenga ve los plazos de esta persona, así que decirlo es parte de
 * entregarla.
 */
import * as React from "react";
import { CalendarPlus, Check, Copy } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useCalendarioEnlace } from "@/hooks/use-calendario";

export function CalendarioSuscripcion() {
  const { data, isLoading, error } = useCalendarioEnlace();
  const [copiado, setCopiado] = React.useState(false);

  // El origen sólo existe en el cliente; en el render de servidor la URL
  // absoluta se deja vacía en vez de inventar un host. `useSyncExternalStore`
  // y no un efecto con `setState`: el valor no cambia nunca en la vida de la
  // página, así que no hay nada que sincronizar y un efecto sólo añadiría un
  // render en cascada.
  const origen = React.useSyncExternalStore(
    () => () => {},
    () => window.location.origin,
    () => "",
  );

  const urlAbsoluta = data && origen ? `${origen}${data.path}` : "";

  const copiar = async () => {
    if (!urlAbsoluta) return;
    try {
      await navigator.clipboard.writeText(urlAbsoluta);
      setCopiado(true);
      toast.success("Enlace copiado");
      window.setTimeout(() => setCopiado(false), 2000);
    } catch {
      toast.error("No se pudo copiar. Selecciona la URL y cópiala a mano.");
    }
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm">
          <CalendarPlus aria-hidden="true" />
          Calendario
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[360px] space-y-2.5">
        <h3 className="text-[13px] font-semibold">Suscríbete a tus plazos</h3>

        {error ? (
          <p className="text-[11.5px] leading-[1.5] text-destructive">
            No se pudo generar el enlace del calendario.
          </p>
        ) : (
          <>
            <p className="text-[11.5px] leading-[1.5] text-muted-foreground">
              Añade esta URL en Google Calendar, Apple Calendar u Outlook: los plazos de tus
              oportunidades abiertas y de tus favoritos se actualizan solos.
              {data && ` Hoy contiene ${data.eventos} evento${data.eventos === 1 ? "" : "s"}.`}
            </p>

            <div className="flex items-center gap-1.5">
              <input
                readOnly
                aria-label="URL de suscripción al calendario"
                value={isLoading ? "Generando enlace…" : urlAbsoluta}
                className="h-8 min-w-0 flex-1 rounded-md border border-input bg-background px-2 font-mono text-[11px]"
                onFocus={(event) => event.currentTarget.select()}
              />
              <Button
                size="sm"
                variant="secondary"
                disabled={!urlAbsoluta}
                onClick={() => void copiar()}
              >
                {copiado ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                {copiado ? "Copiado" : "Copiar"}
              </Button>
            </div>

            <p className="text-[10.5px] leading-[1.45] text-muted-foreground">
              El enlace lleva una firma personal: quien lo tenga ve tus plazos. Si se filtra, pide
              una rotación de claves.
            </p>

            {data && (
              <a
                href={data.path}
                target="_blank"
                rel="noreferrer"
                className="inline-block text-[11.5px] font-medium"
              >
                Descargar .ics
              </a>
            )}
          </>
        )}
      </PopoverContent>
    </Popover>
  );
}
