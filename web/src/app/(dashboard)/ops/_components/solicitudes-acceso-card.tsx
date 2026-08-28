"use client";

/**
 * Cola de solicitudes de acceso llegadas desde la landing.
 *
 * Antes de que existiera esta cola, el CTA público acababa en un `mailto:` y la
 * petición vivía en el buzón de alguien. Aquí se ve qué ha entrado y se marca
 * como atendida o descartada.
 *
 * **Marcar una solicitud como atendida no concede el acceso.** La allowlist
 * sigue en `OAUTH_ALLOWED_EMAILS`/`OAUTH_ALLOWED_DOMAINS`, así que habilitar a
 * alguien es editar variables de entorno y redesplegar; el estado de aquí sólo
 * dice si la petición ya se ha tratado. La tarjeta lo declara en su cabecera
 * para que nadie asuma lo contrario.
 *
 * Vive en su propio fichero y no dentro de `administracion-view.tsx`, que ya
 * pasa de 800 líneas y está en el roadmap de descomposición del UX_AUDIT.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Inbox } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiMutate } from "@/lib/api-client";
import { formatDate } from "@/lib/utils";

interface SolicitudAcceso {
  id: number;
  email: string;
  empresa?: string | null;
  mensaje?: string | null;
  origen?: string | null;
  estado: string;
  created_at?: string | null;
}

/**
 * Respuesta del PATCH. `notificado` es `null` cuando no se pidió aviso, y
 * `false` cuando se pidió y no salió: son casos distintos y se cuentan distinto.
 */
interface CambioEstado {
  status: string;
  notificado: boolean | null;
}

const ETIQUETA_ESTADO: Record<string, string> = {
  pendiente: "Pendiente",
  atendida: "Atendida",
  descartada: "Descartada",
};

export function SolicitudesAccesoCard() {
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery<SolicitudAcceso[]>({
    queryKey: ["admin-solicitudes-acceso"],
    queryFn: async () => {
      const res = await fetch("/api/v1/admin/solicitudes-acceso", { credentials: "include" });
      if (res.status === 401) throw new Error("Sesión expirada");
      if (res.status === 403) throw new Error("Requiere permisos de admin");
      if (!res.ok) throw new Error(`Error ${res.status}`);
      return res.json();
    },
  });

  const cambiarEstado = useMutation({
    mutationFn: (vars: { id: number; estado: string; notificar?: boolean }) =>
      apiMutate<CambioEstado>("PATCH", `/api/v1/admin/solicitudes-acceso/${vars.id}`, {
        estado: vars.estado,
        notificar: vars.notificar ?? false,
      }),
    onSuccess: (respuesta) => {
      queryClient.invalidateQueries({ queryKey: ["admin-solicitudes-acceso"] });
      // `notificado` distingue tres cosas y las tres importan: no se pidió
      // aviso (`null`), salió (`true`), o se pidió y NO salió (`false`). Sin
      // este reparto, un SMTP mal configurado dejaba al operador convencido de
      // que había avisado a alguien a quien nadie escribió — que es justo el
      // fallo silencioso que el campo existe para delatar.
      if (respuesta?.notificado === true) {
        toast.success("Solicitud atendida y aviso enviado");
      } else if (respuesta?.notificado === false) {
        toast.warning("Solicitud atendida, pero el aviso no salió", {
          description: "Revisa la configuración de correo o escríbele a mano.",
        });
      } else {
        toast.success("Solicitud actualizada");
      }
    },
    onError: () => toast.error("No se pudo actualizar la solicitud"),
  });

  const solicitudes = data ?? [];
  const pendientes = solicitudes.filter((s) => s.estado === "pendiente").length;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Inbox className="h-4 w-4" aria-hidden="true" />
          Solicitudes de acceso
          {pendientes > 0 && <Badge variant="secondary">{pendientes} pendientes</Badge>}
        </CardTitle>
        <CardDescription>
          Peticiones enviadas desde el formulario de la web pública. Marcarlas aquí no concede el acceso: la allowlist
          sigue en las variables de entorno del despliegue. El orden es habilitar la dirección, esperar al reinicio y
          solo entonces «Atendida y avisar», que es lo que escribe a la persona.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading && <Skeleton className="h-24 w-full" />}
        {error && <p className="text-destructive text-sm">{(error as Error).message}</p>}
        {!isLoading && !error && solicitudes.length === 0 && (
          <p className="text-muted-foreground text-sm">Todavía no ha llegado ninguna solicitud.</p>
        )}
        {!isLoading && !error && solicitudes.length > 0 && (
          <ul className="divide-border/60 divide-y">
            {solicitudes.map((solicitud) => (
              <li key={solicitud.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium">{solicitud.email}</p>
                  <p className="text-muted-foreground mt-0.5 text-xs">
                    {[solicitud.empresa, solicitud.origen, formatDate(solicitud.created_at ?? undefined)]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                  {solicitud.mensaje && (
                    <p className="text-muted-foreground mt-1 max-w-[70ch] text-xs leading-relaxed">
                      {solicitud.mensaje}
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Badge variant={solicitud.estado === "pendiente" ? "default" : "outline"}>
                    {ETIQUETA_ESTADO[solicitud.estado] ?? solicitud.estado}
                  </Badge>
                  {solicitud.estado === "pendiente" && (
                    <>
                      {/* El aviso va en su propio botón, y no de propina al
                          marcar atendida, porque el correo afirma «ya puedes
                          entrar»: mandarlo antes de haber editado la allowlist
                          manda a la persona contra un 403. El orden correcto
                          está en docs/runbooks/conceder-acceso.md. */}
                      <Button
                        size="sm"
                        disabled={cambiarEstado.isPending}
                        title="Marca la solicitud y escribe a la persona. Úsalo solo si ya has añadido su dirección o su dominio a la allowlist y el servicio ha reiniciado."
                        onClick={() =>
                          cambiarEstado.mutate({
                            id: solicitud.id,
                            estado: "atendida",
                            notificar: true,
                          })
                        }
                      >
                        Atendida y avisar
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={cambiarEstado.isPending}
                        title="Solo marca la solicitud como tratada. No escribe a nadie."
                        onClick={() => cambiarEstado.mutate({ id: solicitud.id, estado: "atendida" })}
                      >
                        Atendida
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={cambiarEstado.isPending}
                        title="Cierra la solicitud sin escribir a nadie."
                        onClick={() => cambiarEstado.mutate({ id: solicitud.id, estado: "descartada" })}
                      >
                        Descartar
                      </Button>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
