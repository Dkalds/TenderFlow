"use client";

/**
 * Adjuntos del equipo en la ficha de la oportunidad (C6.3, CU-27).
 *
 * La pestaña Expediente enseña los documentos del pliego; aquí van los que el
 * equipo escribe para responderlo: la propuesta, los anexos, el presupuesto. El
 * backend tenía subida, listado, descarga firmada y retirada desde C6.3, y la
 * consola no tenía ninguna pantalla que los usara.
 *
 * Tres cosas las dicta el servidor y aquí solo se leen:
 *
 * - **Si el entorno acepta adjuntos.** Sin almacén de objetos (ADR-029) la
 *   subida respondería 503 después de enviar el fichero; la política lo dice
 *   antes, y la pantalla lo cuenta en vez de ofrecer un botón que siempre falla.
 * - **El tope y los tipos.** Vienen de `GET /pursuits/adjuntos/politica`, las
 *   mismas constantes con las que el servidor valida; avisar antes solo ahorra
 *   subir 25 MB para oír que no.
 * - **Quién escribe.** Un `viewer` ve y descarga, pero no sube ni retira: el
 *   botón no aparece (`usePuedeEscribir`) y la API lo rechazaría igual.
 */
import * as React from "react";
import { Download, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { Aviso, Panel, PanelEmpty, PanelError, PanelLoading, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { usePuedeEscribir } from "@/hooks/use-organization";
import {
  useDescargarAdjunto,
  usePoliticaAdjuntos,
  usePursuitAdjuntos,
  useRetirarAdjunto,
  useSubirAdjunto,
} from "@/hooks/use-pursuit-adjuntos";
import { extensionesAdmitidas, validarFichero, type Adjunto } from "@/lib/adjuntos";
import { formatDate, formatTamano } from "@/lib/utils";

export function AdjuntosPanel({ pursuitId }: { pursuitId: number }) {
  const politica = usePoliticaAdjuntos();
  const adjuntos = usePursuitAdjuntos(pursuitId);
  const puedeEscribir = usePuedeEscribir();
  const subir = useSubirAdjunto(pursuitId);
  const selector = React.useRef<HTMLInputElement>(null);
  const idTitulo = React.useId();

  const almacen = politica.data?.almacen_disponible ?? false;
  const admitidas = politica.data ? extensionesAdmitidas(politica.data) : [];

  const elegir = (evento: React.ChangeEvent<HTMLInputElement>) => {
    const fichero = evento.target.files?.[0];
    // Se vacía el selector siempre: elegir otra vez el mismo fichero tras un
    // fallo tiene que volver a disparar `change`.
    evento.target.value = "";
    if (!fichero || !politica.data) return;
    const validacion = validarFichero(fichero, politica.data);
    if (!validacion.ok) {
      toast.error(`No se puede subir «${fichero.name}»`, { description: validacion.motivo });
      return;
    }
    subir.mutate(
      { fichero, contentType: validacion.contentType },
      {
        onSuccess: () => toast.success(`«${fichero.name}» adjuntado a la oportunidad`),
      },
    );
  };

  const ofreceSubida = puedeEscribir && almacen;

  return (
    <Panel>
      <section aria-labelledby={idTitulo}>
        <PanelTitle
          id={idTitulo}
          title="Adjuntos del equipo"
          hint="La propuesta y sus anexos; solo los ve tu organización"
          actions={
            ofreceSubida ? (
              <>
                <input
                  ref={selector}
                  type="file"
                  className="hidden"
                  accept={admitidas.join(",")}
                  onChange={elegir}
                  aria-label="Elegir el fichero que se adjunta"
                />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={subir.isPending}
                  onClick={() => selector.current?.click()}
                >
                  <Upload aria-hidden="true" />
                  {subir.isPending ? "Subiendo…" : "Subir adjunto"}
                </Button>
              </>
            ) : undefined
          }
        />

        {politica.data && !almacen && (
          <Aviso tone="warning" title="Este entorno no guarda documentos" className="mb-3">
            No tiene almacén de documentos configurado, así que no se pueden subir adjuntos ni descargar los que
            hubiera. Lo configura quien administra la instalación.
          </Aviso>
        )}
        {politica.error && (
          <PanelError
            variant="inline"
            title="No se pudo saber si este entorno admite adjuntos"
            error={politica.error}
            onRetry={() => void politica.refetch()}
          />
        )}
        {ofreceSubida && politica.data && (
          <p className="text-muted-foreground mb-3 text-tf-meta">
            Hasta {formatTamano(politica.data.max_bytes)} por fichero. Se admiten {admitidas.join(", ")}.
          </p>
        )}
        {!puedeEscribir && (
          <p className="text-muted-foreground mb-3 text-tf-meta">
            Tienes acceso de lectura: puedes ver y descargar los adjuntos, pero no subir ni retirar.
          </p>
        )}

        <ListaAdjuntos
          pursuitId={pursuitId}
          adjuntos={adjuntos.data}
          cargando={adjuntos.isPending}
          error={adjuntos.error}
          onReintentar={() => void adjuntos.refetch()}
          puedeRetirar={puedeEscribir}
          puedeDescargar={almacen}
        />
      </section>
    </Panel>
  );
}

function ListaAdjuntos({
  pursuitId,
  adjuntos,
  cargando,
  error,
  onReintentar,
  puedeRetirar,
  puedeDescargar,
}: {
  pursuitId: number;
  adjuntos: Adjunto[] | undefined;
  cargando: boolean;
  error: unknown;
  onReintentar: () => void;
  puedeRetirar: boolean;
  puedeDescargar: boolean;
}) {
  if (cargando) return <PanelLoading height={96} />;
  if (error) {
    return <PanelError variant="inline" title="No se pudieron cargar los adjuntos" error={error} onRetry={onReintentar} />;
  }
  if (!adjuntos || adjuntos.length === 0) {
    return (
      <PanelEmpty
        size="sm"
        title="Sin adjuntos todavía"
        hint="Aquí van la propuesta, los anexos o el presupuesto que prepara el equipo para esta oportunidad."
      />
    );
  }
  return (
    <ul className="divide-divider divide-y" aria-label="Adjuntos de la oportunidad">
      {adjuntos.map((adjunto) => (
        <FilaAdjunto
          key={adjunto.id}
          pursuitId={pursuitId}
          adjunto={adjunto}
          puedeRetirar={puedeRetirar}
          puedeDescargar={puedeDescargar}
        />
      ))}
    </ul>
  );
}

function FilaAdjunto({
  pursuitId,
  adjunto,
  puedeRetirar,
  puedeDescargar,
}: {
  pursuitId: number;
  adjunto: Adjunto;
  puedeRetirar: boolean;
  puedeDescargar: boolean;
}) {
  const descargar = useDescargarAdjunto();
  const retirar = useRetirarAdjunto(pursuitId);
  // Retirar en dos pasos y dentro de la fila, como borrar un comentario: sin
  // modal, pero sin que un clic perdido se lleve la propuesta de un compañero.
  const [confirmando, setConfirmando] = React.useState(false);
  const autor = adjunto.uploaded_by_name ?? "alguien que ya no está en el equipo";

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5">
      <div className="min-w-0 flex-1">
        {/* El nombre entero y partido donde haga falta, sin recortar: dos
            versiones de la misma propuesta suelen diferir solo en el final. */}
        <p className="break-words text-tf-body font-medium">{adjunto.filename}</p>
        <p className="text-muted-foreground text-tf-meta">
          {formatTamano(adjunto.size_bytes)} · subido por {autor} el {formatDate(adjunto.created_at)}
        </p>
      </div>
      {confirmando ? (
        <div role="group" aria-label="Confirmar retirada" className="flex items-center gap-1.5 text-tf-meta">
          <span className="text-muted-foreground">¿Retirar este adjunto?</span>
          <Button
            type="button"
            size="sm"
            variant="destructive"
            disabled={retirar.isPending}
            onClick={() =>
              retirar.mutate(adjunto.id, {
                onSuccess: () => toast.success(`«${adjunto.filename}» retirado de la oportunidad`),
                onError: () => setConfirmando(false),
              })
            }
          >
            Retirar
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setConfirmando(false)}>
            Cancelar
          </Button>
        </div>
      ) : (
        <div className="flex flex-none items-center gap-1.5">
          {puedeDescargar && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={descargar.isPending}
              aria-label={`Descargar ${adjunto.filename}`}
              onClick={() =>
                descargar.mutate(adjunto)
              }
            >
              <Download aria-hidden="true" />
              Descargar
            </Button>
          )}
          {puedeRetirar && (
            <Button
              type="button"
              size="icon-sm"
              variant="ghost"
              aria-label={`Retirar ${adjunto.filename}`}
              className="text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
              onClick={() => setConfirmando(true)}
            >
              <Trash2 aria-hidden="true" />
            </Button>
          )}
        </div>
      )}
    </li>
  );
}
