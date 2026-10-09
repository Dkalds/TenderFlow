"use client";

/**
 * Inspector en el mismo plano: el detalle del compromiso seleccionado.
 *
 * Cada clase de compromiso enseña lo suyo, porque lo que hace falta para
 * decidir es distinto: una oportunidad o una tarea piden sus dos fechas y la
 * lista de tareas; un contrato, su fin efectivo con el origen y la ventana de
 * relicitación; una señal, la regla que la trajo. La cabecera y los datos
 * comunes son los mismos para las cinco.
 *
 * **Lo que se hace con el compromiso va arriba**, justo bajo el título, y los
 * datos después. Estaba al revés —las acciones al final de un panel de 690 px—
 * y en un portátil «Abrir ficha» caía fuera de la pantalla. Si aun así el panel
 * no cabe, se desplaza él y no la página.
 *
 * **De una oportunidad por cerrar no se ofrece planificar.** Ya no admite
 * oferta: enseñarle el formulario de tareas y una «Próxima acción» vacía era
 * invitar a apuntar el siguiente paso de algo que no lo tiene. En su lugar va
 * lo que hace falta para cerrarla: en qué quedó la licitación y quién se la
 * llevó, si se sabe.
 *
 * Decisión escrita: el inspector no baja de `xl`. Lo accionable de cada
 * compromiso ya está en su ficha (abrir / completar / preparar renovación /
 * seguir / descartar / apuntar la próxima acción), así que en móvil no se
 * pierde ninguna decisión. Lo que sí queda fuera es la lista de tareas de la
 * oportunidad: en 375 px pide una hoja a pantalla completa, no un panel lateral
 * encogido, y eso es trabajo aparte — anotado como pendiente, no resuelto con
 * un `hidden`.
 */

import type { ReactNode } from "react";
import { ExternalLink } from "lucide-react";
import { AvisoPestanaNueva } from "@/components/ui/aviso-pestana-nueva";
import { cn, EMPTY, formatCompactCurrency, formatDate, truncate } from "@/lib/utils";
import { estadoLabel } from "@/lib/estados";
import { PanelEmpty, ROTULO_DATO } from "@/components/console/panel";
import { Button, buttonVariants } from "@/components/ui/button";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";
import type { Agenda } from "../../_hooks/use-agenda";
import { AgendaContrato } from "./agenda-contrato";
import { AgendaFechas } from "./agenda-fechas";
import { AgendaSenal } from "./agenda-senal";
import { AgendaTareas } from "./agenda-tareas";
import { bandaDe, claseChip, claveDe, etiquetaKind } from "./agenda-meta";
import { estadoDeFila, plazoChip, tipoDeFecha, tituloDe } from "./agenda-texto";

function Dato({ label, valor }: { label: string; valor: ReactNode }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="flex-none text-muted-foreground">{label}</dt>
      <dd className="min-w-0 truncate text-right">{valor}</dd>
    </div>
  );
}

function Cabecera({ item }: { item: PipelineAgendaItem }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5">
        <span
          className={cn(
            "tf-tnum inline-flex h-5 items-center rounded-full px-2 text-tf-micro font-semibold",
            claseChip(item),
          )}
        >
          {plazoChip(item)}
        </span>
        <span className={ROTULO_DATO}>{etiquetaKind(item)}</span>
      </div>
      <h3 className="text-tf-body font-semibold">{tituloDe(item)}</h3>
      <p className="mt-1 text-tf-micro text-muted-foreground">
        {tipoDeFecha(item)}
        {item.due_date ? ` · ${formatDate(item.due_date)}` : " · sin fecha"}
        {item.due_hora ? `, ${item.due_hora}` : ""}
      </p>
    </div>
  );
}

const PRIMARIO = "border-primary/30 bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary";

export function AgendaInspector({ agenda }: { agenda: Agenda }) {
  const item = agenda.active;
  const esPursuitOTarea = item?.kind === "pursuit" || item?.kind === "tarea";
  const porCerrar = item?.kind === "pursuit" && bandaDe(item) === "plazo_pasado";
  const estado = item ? estadoDeFila(item) : null;

  return (
    <aside
      aria-label="Detalle del compromiso"
      className="hidden min-w-0 self-start rounded-xl border border-border/60 bg-card p-4 xl:block xl:max-h-full xl:overflow-y-auto"
    >
      {!item ? (
        <PanelEmpty size="sm" hint="Selecciona un compromiso para ver su detalle." />
      ) : (
        <div className="space-y-4">
          <Cabecera item={item} />

          {(item.kind !== "senal" || item.url) && (
            <div className="flex flex-wrap gap-1.5">
              {item.kind !== "senal" && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => agenda.abrir(item)}
                  className={cn("flex-1", PRIMARIO)}
                >
                  {item.kind === "renovacion" ? "Anticipar oportunidad" : "Abrir ficha"}
                </Button>
              )}
              {porCerrar && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => agenda.pedirRetirada([item])}
                  className="text-muted-foreground hover:text-foreground"
                >
                  No nos presentamos
                </Button>
              )}
              {item.url && (
                // Enlace a la página del expediente en PLACSP, nunca al documento:
                // los enlaces directos a pliegos llevan tokens rotativos y caducan.
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={buttonVariants({
                    variant: "outline",
                    size: "sm",
                    className: "text-muted-foreground hover:text-foreground",
                  })}
                >
                  PLACSP
                  <ExternalLink aria-hidden="true" />
                  <AvisoPestanaNueva />
                </a>
              )}
            </div>
          )}

          {item.kind === "senal" && (
            <AgendaSenal
              item={item}
              onSeguir={() => void agenda.seguir(item)}
              onDescartar={() => agenda.descartar(item)}
              onPosponer={() => agenda.posponer(item)}
            />
          )}

          <dl className="space-y-1.5 border-t border-border/50 pt-3 text-tf-meta">
            {item.organo && <Dato label="Órgano" valor={truncate(item.organo, 40)} />}
            <Dato
              label="Importe"
              valor={
                <span className="tf-tnum">
                  {item.importe_eur != null ? formatCompactCurrency(item.importe_eur) : EMPTY}
                </span>
              }
            />
            {item.ccaa && <Dato label="CCAA" valor={item.ccaa} />}
            {estado && <Dato label="Estado" valor={estado} />}
            {item.responsible_name && <Dato label="Responsable" valor={item.responsible_name} />}
            {/* Lo que la ingesta sabe de la licitación, cuando ya está cerrada:
                es lo que permite decidir cómo se cierra la oportunidad. */}
            {item.kind === "pursuit" && item.expediente_cerrado && (
              <Dato label="Licitación" valor={estadoLabel(item.expediente_estado) || "Cerrada"} />
            )}
            {(item.kind === "renovacion" || item.kind === "pursuit") && item.adjudicatario && (
              <Dato label="Adjudicatario" valor={truncate(item.adjudicatario, 36)} />
            )}
            {item.kind === "renovacion" && item.riesgo_cambio != null && (
              <Dato
                label="Riesgo de cambio"
                valor={
                  <span className="tf-tnum">
                    {Math.round(item.riesgo_cambio * 100)}%
                  </span>
                }
              />
            )}
          </dl>

          {/* `key` por fila y versión: cambiar de compromiso remonta el editor
              con el valor del servidor, sin efectos que sincronicen estado. */}
          {esPursuitOTarea && (
            <AgendaFechas
              key={`${claveDe(item)}:${item.version ?? 0}`}
              item={item}
              enfoque={agenda.focoAccion}
              soloPlazo={porCerrar}
            />
          )}
          {esPursuitOTarea && !porCerrar && item.pursuit_id != null && (
            <AgendaTareas pursuitId={item.pursuit_id} />
          )}
          {item.kind === "contrato" && (
            <AgendaContrato
              item={item}
              guardandoFechaFin={agenda.guardandoFechaFin}
              onFijarFechaFin={(fecha, alGuardar) => agenda.fijarFechaFin(item, fecha, alGuardar)}
            />
          )}
        </div>
      )}
    </aside>
  );
}
