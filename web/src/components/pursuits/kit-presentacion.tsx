"use client";

/**
 * F2.3 — Kit de presentación: qué documentos exige el pliego, en qué sobre, y
 * cuáles están listos. Va en el Resumen de la ficha, debajo del contraste del
 * pliego: lo que se decide y con qué se presenta, en la misma columna.
 *
 * El responsable de cada documento es el de su **tarea** (C6.1): elegir a
 * alguien crea la tarea «Kit: …» o reasigna la que ya había. Así el reparto
 * aparece también en la agenda y en la próxima acción de la oportunidad, y no
 * en una columna del kit que nadie más lee.
 *
 * Sin documentos extraídos el kit está vacío **y lo dice**: nunca propone una
 * lista genérica (un DEUC y una declaración responsable «por defecto» se
 * darían por leídos del pliego).
 */
import * as React from "react";
import { toast } from "sonner";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Panel, PanelError, PanelLoading, SectionTitle } from "@/components/console/panel";
import { formatDate } from "@/components/pursuits/pursuit-presenters";
import { useOrganizationMembers } from "@/hooks/use-organization";
import {
  type ItemKit,
  registrarKitAbierto,
  resumenKit,
  useAsignarKitItem,
  useMarcarKitItem,
  usePursuitKit,
} from "@/hooks/use-pursuit-kit";

const SOBRES: Array<{ key: ItemKit["sobre"]; titulo: string }> = [
  { key: "sobre_a", titulo: "Sobre A" },
  { key: "sobre_b", titulo: "Sobre B" },
  { key: "sobre_c", titulo: "Sobre C" },
  { key: "otro", titulo: "Otros documentos" },
];

const ESTADO_TAREA: Record<string, string> = {
  pendiente: "tarea pendiente",
  en_curso: "tarea en curso",
  hecha: "tarea hecha",
  descartada: "tarea descartada",
};

const SIN_RESPONSABLE = "sin-responsable";

export function KitPresentacionPanel({
  pursuitId,
  organizationId,
}: {
  pursuitId: number;
  organizationId: number;
}) {
  const { data: kit, isPending, error, refetch } = usePursuitKit(pursuitId);
  const marcar = useMarcarKitItem(pursuitId);
  const asignar = useAsignarKitItem(pursuitId);
  const members = useOrganizationMembers(organizationId).data ?? [];

  const registrado = React.useRef(false);
  React.useEffect(() => {
    if (kit && !registrado.current) {
      registrado.current = true;
      registrarKitAbierto(kit);
    }
  }, [kit]);

  const onError = (mensaje: string) => (err: unknown) =>
    toast.error(err instanceof Error ? err.message : mensaje);

  if (isPending) {
    return (
      <Panel id="ficha-kit">
        <PanelLoading height={160} />
      </Panel>
    );
  }
  if (error || !kit) {
    return (
      <div id="ficha-kit">
        <PanelError
          title="No se pudo cargar el kit de presentación"
          detail={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  const { listos, total } = resumenKit(kit);

  return (
    // El mismo rótulo que el resto de paneles de la ficha; el panel se nombra
    // por él y es el destino del paso «Documentación del kit lista».
    <Panel id="ficha-kit" tabIndex={-1} className="outline-none" aria-labelledby={`kit-${pursuitId}`}>
      <SectionTitle
        aside={total ? `${listos} de ${total} documentos listos` : "Documentos que exige el pliego"}
      >
        <span id={`kit-${pursuitId}`}>Kit de presentación</span>
      </SectionTitle>
      {kit.sin_extraccion || total === 0 ? (
        <p role="status" className="text-tf-meta leading-[1.55] text-muted-foreground">
          No se han extraído documentos exigidos del pliego de este expediente. El kit no propone
          una lista genérica: revisa el pliego en la pestaña «Pliego» antes de dar la oferta por
          completa.
        </p>
      ) : (
        <div className="space-y-4">
          {SOBRES.map((sobre) => {
            const items = (kit.items ?? []).filter((item) => item.sobre === sobre.key);
            if (items.length === 0) return null;
            return (
              <section key={sobre.key} aria-label={sobre.titulo}>
                <h5 className="mb-1.5 font-mono text-tf-micro font-semibold uppercase tracking-wider text-muted-foreground">
                  {sobre.titulo}
                </h5>
                <ul className="divide-y divide-border/50">
                  {items.map((item) => {
                    const checkId = `kit-${pursuitId}-${item.clave}`;
                    const selectId = `${checkId}-responsable`;
                    return (
                      <li
                        key={item.clave}
                        className="flex flex-col gap-2 py-2 sm:flex-row sm:items-center sm:gap-3"
                      >
                        <div className="flex min-w-0 flex-1 items-start gap-2.5">
                          <Checkbox
                            id={checkId}
                            className="mt-0.5"
                            checked={item.listo}
                            disabled={marcar.isPending}
                            onCheckedChange={(value) =>
                              marcar.mutate(
                                { clave: item.clave, listo: value === true },
                                { onError: onError("No se pudo marcar el documento") },
                              )
                            }
                          />
                          <div className="min-w-0">
                            <label
                              htmlFor={checkId}
                              className="text-tf-body leading-snug font-medium"
                            >
                              {item.nombre}
                            </label>
                            <p className="text-tf-micro text-muted-foreground">
                              {item.subsanable === true ? "Subsanable · " : null}
                              {item.listo && item.marcado_en
                                ? `Listo desde ${formatDate(item.marcado_en)}`
                                : "Pendiente"}
                              {item.tarea_estado
                                ? ` · ${ESTADO_TAREA[item.tarea_estado] ?? item.tarea_estado}`
                                : null}
                              {item.tarea_vence ? ` · vence ${formatDate(item.tarea_vence)}` : null}
                            </p>
                          </div>
                        </div>
                        <div className="sm:w-52">
                          <label htmlFor={selectId} className="sr-only">
                            Responsable de {item.nombre}
                          </label>
                          <Select
                            value={item.responsable_user_id ? String(item.responsable_user_id) : SIN_RESPONSABLE}
                            disabled={asignar.isPending}
                            onValueChange={(value) => {
                              if (value === SIN_RESPONSABLE) return;
                              asignar.mutate(
                                { clave: item.clave, responsable_user_id: Number(value) },
                                {
                                  onSuccess: () => toast.success("Responsable asignado: tarea creada"),
                                  onError: onError("No se pudo asignar el documento"),
                                },
                              );
                            }}
                          >
                            <SelectTrigger id={selectId} className="h-8 text-tf-meta">
                              <SelectValue placeholder="Sin responsable" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value={SIN_RESPONSABLE} disabled>
                                Sin responsable
                              </SelectItem>
                              {members.map((member) => (
                                <SelectItem key={member.user_id} value={String(member.user_id)}>
                                  {member.display_name ?? member.email ?? `Usuario ${member.user_id}`}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}
          <p className="text-tf-micro leading-[1.5] text-muted-foreground">
            Asignar un documento crea una tarea con su nombre. Si la tarea se borra, el documento
            vuelve a quedar sin responsable.
          </p>
        </div>
      )}
    </Panel>
  );
}
