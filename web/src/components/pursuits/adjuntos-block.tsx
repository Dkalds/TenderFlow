"use client";

/**
 * Los documentos del equipo, dentro de la pestaña Expediente (C6.3).
 *
 * Van debajo de los del órgano y con rótulo propio porque **no son lo mismo**:
 * el pliego es dato público del expediente y esto es trabajo de la
 * organización. La diferencia se nota en tres sitios de esta pantalla — quién
 * puede verlos (sólo el equipo), cómo se descargan (enlace firmado que caduca a
 * los quince minutos, no la sesión) y si el asistente los lee (no, salvo que
 * alguien lo autorice fichero a fichero).
 *
 * El interruptor de «lo lee el asistente» está aquí y no en Ajustes a
 * propósito: la decisión es distinta para el DEUC —que no dice nada que el
 * pliego no diga— que para la propuesta económica, y una preferencia de
 * organización obligaría a tomarla una sola vez para las dos.
 */
import * as React from "react";
import { Download, FileText, Loader2, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { PanelEmpty, PanelError } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  useAdjuntoIndexable,
  useBorrarAdjunto,
  useDescargarAdjunto,
  usePursuitAttachments,
  useSubirAdjunto,
} from "@/hooks/use-pursuit-attachments";
import { ApiError } from "@/lib/api-client";
import { formatDateTime } from "@/lib/utils";

/** Tamaño legible. No usa `Intl` porque el redondeo a una decimal basta. */
function pesoLegible(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function mensajeDeError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "No se pudo completar la operación";
}

export function AdjuntosBlock({ pursuitId }: { pursuitId: number }) {
  const { data, isLoading, error, refetch } = usePursuitAttachments(pursuitId);
  const subir = useSubirAdjunto(pursuitId);
  const borrar = useBorrarAdjunto(pursuitId);
  const indexable = useAdjuntoIndexable(pursuitId);
  const descargar = useDescargarAdjunto(pursuitId);
  const inputRef = React.useRef<HTMLInputElement>(null);

  if (isLoading) return <Skeleton className="h-24 w-full rounded-md" />;

  if (error) {
    return (
      <PanelError
        title="No se pudieron cargar los adjuntos"
        detail={mensajeDeError(error)}
        onRetry={() => void refetch()}
        height={140}
      />
    );
  }

  const items = data?.items ?? [];
  const maxBytes = data?.max_bytes ?? 0;
  const tipos = data?.tipos_admitidos ?? [];

  async function alElegir(event: React.ChangeEvent<HTMLInputElement>) {
    const fichero = event.target.files?.[0];
    // El input se limpia SIEMPRE: sin esto, elegir el mismo fichero dos veces
    // seguidas —tras un error, que es justo cuando se reintenta— no dispara
    // `change` y la pantalla parece congelada.
    event.target.value = "";
    if (!fichero) return;
    // El tope se comprueba también aquí, con la cifra que dio la API: subir
    // 40 MB para que el servidor los rechace son dos minutos de espera para
    // llegar al mismo sitio.
    if (maxBytes > 0 && fichero.size > maxBytes) {
      toast.error(`«${fichero.name}» ocupa ${pesoLegible(fichero.size)}`, {
        description: `El máximo por fichero son ${pesoLegible(maxBytes)}.`,
      });
      return;
    }
    try {
      await subir.mutateAsync(fichero);
      toast.success(`«${fichero.name}» subido`);
    } catch (err) {
      toast.error("No se pudo subir el fichero", { description: mensajeDeError(err) });
    }
  }

  async function alDescargar(attachmentId: number, nombre: string) {
    try {
      const enlace = await descargar.mutateAsync(attachmentId);
      // `noopener` explícito: el destino es una descarga y no debe poder tocar
      // la pestaña que la abrió.
      window.open(enlace.url, "_blank", "noopener,noreferrer");
    } catch (err) {
      toast.error(`No se pudo descargar «${nombre}»`, { description: mensajeDeError(err) });
    }
  }

  async function alBorrar(attachmentId: number, nombre: string) {
    try {
      await borrar.mutateAsync(attachmentId);
      toast.success(`«${nombre}» borrado`);
    } catch (err) {
      toast.error(`No se pudo borrar «${nombre}»`, { description: mensajeDeError(err) });
    }
  }

  async function alCambiarIndexable(attachmentId: number, valor: boolean) {
    try {
      await indexable.mutateAsync({ attachmentId, indexable: valor });
    } catch (err) {
      toast.error("No se pudo cambiar el permiso", { description: mensajeDeError(err) });
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {items.length === 0 ? (
        <PanelEmpty message="La propuesta, el DEUC o el aval van aquí, junto a la oportunidad y no en un correo." />
      ) : (
        <ul className="flex flex-col divide-y divide-border/60">
          {items.map((adjunto) => (
            <li key={adjunto.id} className="flex items-center gap-2.5 py-2">
              <FileText className="h-4 w-4 flex-none text-muted-foreground" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[12.5px] font-medium">{adjunto.filename}</div>
                <div className="text-[11px] text-muted-foreground">
                  {pesoLegible(adjunto.bytes)}
                  {adjunto.created_at ? ` · ${formatDateTime(adjunto.created_at)}` : ""}
                </div>
              </div>
              {/* `<span>` y no `<label>`: el control es un `Switch` de Radix, que
                  ya trae su propio nombre accesible con el nombre del fichero
                  dentro. Un `<label>` alrededor prometería una asociación que
                  `htmlFor` no está haciendo, y el rótulo visible es una
                  abreviatura —«Lo lee el asistente»— que sin el nombre del
                  fichero se repetiría idéntica en cada fila. */}
              <span className="flex flex-none items-center gap-1.5 text-[11px] text-muted-foreground">
                <Switch
                  checked={adjunto.indexable ?? false}
                  onCheckedChange={(valor) => void alCambiarIndexable(adjunto.id, valor)}
                  aria-label={`Permitir que el asistente lea «${adjunto.filename}»`}
                />
                <span aria-hidden="true" className="hidden sm:inline">
                  Lo lee el asistente
                </span>
              </span>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Descargar «${adjunto.filename}»`}
                onClick={() => void alDescargar(adjunto.id, adjunto.filename)}
              >
                <Download className="h-4 w-4" aria-hidden="true" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Borrar «${adjunto.filename}»`}
                onClick={() => void alBorrar(adjunto.id, adjunto.filename)}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex items-center gap-2">
        {/* El input está oculto y quien lo abre es el botón de al lado, que sí
            es el control visible. Lleva `aria-label` porque para el lector de
            pantalla sigue siendo un control real, no un detalle de implementación. */}
        <input
          ref={inputRef}
          type="file"
          className="sr-only"
          aria-label="Elegir un documento del equipo para subir"
          accept={tipos.join(",")}
          onChange={(event) => void alElegir(event)}
        />
        <Button
          variant="outline"
          size="sm"
          disabled={subir.isPending}
          onClick={() => inputRef.current?.click()}
        >
          {subir.isPending ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          ) : (
            <Upload className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          )}
          Subir documento
        </Button>
        {maxBytes > 0 && (
          <span className="text-[11px] text-muted-foreground">
            Hasta {pesoLegible(maxBytes)} por fichero
          </span>
        )}
      </div>

      <p className="text-[11px] leading-[1.5] text-muted-foreground">
        Sólo los ve tu organización. El asistente no los lee salvo que lo actives fichero a
        fichero.
      </p>
    </div>
  );
}
