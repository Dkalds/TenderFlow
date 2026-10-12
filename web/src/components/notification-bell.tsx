"use client";

/**
 * La campana: lo que te concierne en la organización activa.
 *
 * Solo lo tuyo (decisión de producto del 2026-10-12): alertas de tus reglas,
 * cambios en lo que sigues, menciones, tareas y plazos de tus oportunidades y
 * avisos de tu organización. Hasta entonces mezclaba contadores de mercado,
 * licitaciones en vivo por SSE y una lista de novedades que salía siempre
 * vacía; el mercado lo cubre el Resumen, y el SSE dejaba ocupada una plaza de
 * concurrencia de la API por pestaña para enseñar algo que no era de nadie.
 *
 * Abrirla **no** marca nada: cada aviso se marca al abrirlo, y «Marcar todo
 * como leído» es una acción aparte. Marcarlo todo al abrir hacía que el número
 * bajara a cero por mirar el menú, y lo que no cabía en él se perdía sin leer.
 */

import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { Bell } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { buttonVariants } from "@/components/ui/button";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import { registrarEvento } from "@/lib/analytics";
import { apiMutate } from "@/lib/api-client";
import { pursuitKeys, radarKeys } from "@/lib/query-keys";
import { reportError } from "@/lib/report-error";
import { cn } from "@/lib/utils";
import {
  type Aviso,
  AVISOS_EN_VISTA_PREVIA,
  cambiarActivaRegla,
  destinoDeAviso,
  refrescarReglas,
  useAvisos,
  useMarcarLeidos,
} from "./campana/avisos";

// «Ver todas» solo se descarga cuando alguien la abre: la campana viaja en el
// First Load de todas las pantallas.
const VerTodasSheet = dynamic(() => import("./campana/ver-todas-sheet").then((m) => m.VerTodasSheet));

/** Refresco del distintivo con la pestaña a la vista. */
const REFRESCO_MS = 5 * 60_000;

const CLASE_SECUNDARIA = "h-6 px-1.5 py-0 text-tf-micro text-muted-foreground";

export function NotificationBell() {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  const [verTodas, setVerTodas] = React.useState(false);
  const vistaPrevia = useAvisos(organizationId, { refetchInterval: REFRESCO_MS });
  const marcar = useMarcarLeidos(organizationId);

  const avisos = vistaPrevia.data?.items ?? [];
  const sinLeer = vistaPrevia.data?.sin_leer ?? 0;
  const total = vistaPrevia.data?.total ?? 0;

  const abrir = (aviso: Aviso) => {
    if (!aviso.read) marcar.mutate({ ids: [aviso.id] });
  };

  const silenciarRegla = (ruleId: number) => void pausarRegla(queryClient, ruleId, organizationId);

  return (
    <>
      <DropdownMenu>
        {/* La talla de la barra de ámbito (`icon-sm`), junto a «Exportar» y
            «Buscar». El recuento es la señal de «hay algo nuevo», no un error:
            va en el primario, no en rojo. */}
        <DropdownMenuTrigger
          className={cn(buttonVariants({ variant: "ghost", size: "icon-sm" }), "relative")}
          aria-label={`Notificaciones${sinLeer > 0 ? ` (${sinLeer} sin leer)` : ""}`}
        >
          <Bell aria-hidden="true" />
          {sinLeer > 0 && (
            <span
              aria-hidden="true"
              className="tf-tnum absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-tf-micro leading-none font-semibold text-primary-foreground"
            >
              {sinLeer > 99 ? "99+" : sinLeer}
            </span>
          )}
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-80 p-2">
          <div className="mb-1 flex items-center justify-between gap-2 px-2">
            <h4 className="text-tf-meta font-semibold text-muted-foreground">Notificaciones</h4>
            {sinLeer > 0 && (
              <DropdownMenuItem
                className={CLASE_SECUNDARIA}
                // Sin cerrar el menú: lo natural tras marcar es seguir mirando.
                onSelect={(event) => {
                  event.preventDefault();
                  marcar.mutate("todos");
                }}
              >
                Marcar todo como leído
              </DropdownMenuItem>
            )}
          </div>

          {avisos.length === 0 ? (
            <p className="px-2 py-4 text-center text-tf-body text-muted-foreground">
              {vistaPrevia.isError
                ? "No se pudieron cargar tus avisos."
                : "Nada por ahora. Aquí llegan las alertas de tus reglas, las menciones y los plazos de tus oportunidades."}
            </p>
          ) : (
            <ul className="space-y-0.5">
              {avisos.map((aviso) => (
                <FilaAviso key={aviso.id} aviso={aviso} onAbrir={abrir} onSilenciarRegla={silenciarRegla} />
              ))}
            </ul>
          )}

          {total > 0 && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem className="justify-center text-tf-body" onSelect={() => setVerTodas(true)}>
                {total > AVISOS_EN_VISTA_PREVIA ? `Ver todas (${total})` : "Ver todas"}
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {verTodas && (
        <VerTodasSheet
          organizationId={organizationId}
          open={verTodas}
          onOpenChange={setVerTodas}
          onSilenciarRegla={silenciarRegla}
        />
      )}
    </>
  );
}

/**
 * Pone en pausa la regla de una alerta, con «Deshacer». «Ver todas» la recibe
 * como prop: un solo texto y un solo camino para la misma acción.
 */
async function pausarRegla(
  queryClient: ReturnType<typeof useQueryClient>,
  ruleId: number,
  organizationId: ReturnType<typeof useActiveOrganizationId>,
) {
  try {
    const resultado = await cambiarActivaRegla(ruleId, false, organizationId);
    if (resultado === "no_existe") {
      toast.error("Esa regla ya no existe");
      return;
    }
    if (resultado === "sin_cambio") {
      toast("La regla ya estaba en pausa");
      return;
    }
  } catch (err) {
    reportError("NotificationBell.silenciarRegla", err);
    toast.error("No se pudo poner la regla en pausa");
    return;
  }
  void refrescarReglas(queryClient);
  toast("Regla en pausa: deja de avisarte", {
    action: {
      label: "Deshacer",
      onClick: () =>
        void cambiarActivaRegla(ruleId, true, organizationId)
          .then(() => refrescarReglas(queryClient))
          .catch((err: unknown) => reportError("NotificationBell.reactivarRegla", err)),
    },
  });
}

function FilaAviso({
  aviso,
  onAbrir,
  onSilenciarRegla,
}: {
  aviso: Aviso;
  onAbrir: (aviso: Aviso) => void;
  onSilenciarRegla: (ruleId: number) => void;
}) {
  const queryClient = useQueryClient();
  const destino = destinoDeAviso(aviso);
  const titulo = aviso.title ?? aviso.type;

  // F5.6 — silenciar y posponer el expediente con el backend del Radar:
  // `silenciar` lo saca del Radar y de la Agenda hasta que vence; `posponer`
  // además lo devuelve como recordatorio ese día.
  const refrescarRadar = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: radarKeys.dismissals }),
      queryClient.invalidateQueries({ queryKey: radarKeys.scoring }),
      queryClient.invalidateQueries({ queryKey: pursuitKeys.agenda }),
    ]);
  const aplazar = async (idExterno: string, accion: "silenciar" | "posponer", dias: number) => {
    try {
      await apiMutate("POST", "/api/v1/radar/dismissals", {
        id_externo: idExterno,
        score: null,
        banda: null,
        accion,
        dias,
      });
    } catch (err) {
      reportError("NotificationBell.aplazar", err);
      toast.error("No se pudo aplazar el expediente");
      return;
    }
    registrarEvento("radar_triaje", { accion });
    void refrescarRadar();
    toast(accion === "silenciar" ? `Oculta del Radar ${dias} días` : `Te lo recordamos en ${dias} días`, {
      action: {
        label: "Deshacer",
        onClick: () =>
          void apiMutate("DELETE", `/api/v1/radar/dismissals/${encodeURIComponent(idExterno)}`)
            .then(refrescarRadar)
            .catch((err: unknown) => reportError("NotificationBell.deshacer", err)),
      },
    });
  };

  const contenido = (
    <span className="flex min-w-0 items-center gap-2">
      {!aviso.read && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />}
      <span className="truncate">{titulo}</span>
      {!aviso.read && <span className="sr-only">{" (sin leer)"}</span>}
    </span>
  );

  return (
    <li className="flex flex-col">
      {destino ? (
        // `menuitem` y no un enlace suelto: dentro del menú el teclado se mueve
        // con las flechas. Abrirlo lo marca como leído, a él solo.
        <DropdownMenuItem asChild className="text-tf-body" onSelect={() => onAbrir(aviso)}>
          <Link href={destino}>{contenido}</Link>
        </DropdownMenuItem>
      ) : (
        <DropdownMenuItem
          className="text-tf-body"
          aria-label={aviso.read ? titulo : `Marcar como leído: ${titulo}`}
          onSelect={(event) => {
            event.preventDefault();
            onAbrir(aviso);
          }}
        >
          {contenido}
        </DropdownMenuItem>
      )}
      {(aviso.licitacion_id || aviso.rule_id != null) && (
        <div className="flex flex-wrap gap-1 pl-5">
          {aviso.licitacion_id && (
            <>
              <DropdownMenuItem
                className={CLASE_SECUNDARIA}
                aria-label={`Ocultar del Radar 30 días: ${titulo}`}
                onSelect={() => void aplazar(aviso.licitacion_id!, "silenciar", 30)}
              >
                Ocultar del Radar 30 días
              </DropdownMenuItem>
              <DropdownMenuItem
                className={CLASE_SECUNDARIA}
                aria-label={`Recordármelo en 7 días: ${titulo}`}
                onSelect={() => void aplazar(aviso.licitacion_id!, "posponer", 7)}
              >
                Recordármelo en 7 días
              </DropdownMenuItem>
            </>
          )}
          {aviso.rule_id != null && (
            <DropdownMenuItem
              className={CLASE_SECUNDARIA}
              aria-label={`Silenciar esta regla: ${titulo}`}
              onSelect={() => onSilenciarRegla(aviso.rule_id!)}
            >
              Silenciar esta regla
            </DropdownMenuItem>
          )}
        </div>
      )}
    </li>
  );
}
