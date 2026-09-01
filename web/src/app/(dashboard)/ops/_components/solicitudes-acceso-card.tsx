"use client";

/**
 * Cola de solicitudes de acceso llegadas desde la landing.
 *
 * Antes de que existiera esta cola, el CTA público acababa en un `mailto:` y la
 * petición vivía en el buzón de alguien. Aquí se ve qué ha entrado y se marca
 * como atendida o descartada.
 *
 * La acción principal persiste una concesión dinámica antes de notificar. La
 * configuración estática sigue siendo bootstrap, pero las altas normales ya
 * no exigen editar Render ni redesplegar.
 *
 * **La vista por defecto son las pendientes, y no es cosmética.** El endpoint
 * devuelve las N más recientes ordenadas por `created_at DESC` mezclando los
 * tres estados, así que pedirlo sin filtro hacía que, en cuanto la cola
 * histórica superase la ventana, una solicitud pendiente antigua se cayera por
 * abajo sin forma de volver a ella. En un producto de acceso por invitación eso
 * no es una fila perdida en una tabla: es una persona que escribió pidiendo
 * entrar y a la que nunca nadie contestó. Por el mismo motivo el contador de la
 * cabecera sale de su propia consulta filtrada por estado y no de contar
 * pendientes dentro de la ventana que se esté mirando — un contador calculado
 * sobre una lista truncada da siempre la respuesta tranquilizadora.
 *
 * Vive en su propio fichero y no dentro de `administracion-view.tsx`, que ya
 * pasa de 800 líneas y está en el roadmap de descomposición del UX_AUDIT.
 */

import { useState } from "react";
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
  grant_id?: number | null;
}

interface AccessGrant {
  id: number;
  kind: "email" | "domain";
  value: string;
  active: boolean;
}

const ETIQUETA_ESTADO: Record<string, string> = {
  pendiente: "Pendiente",
  atendida: "Atendida",
  descartada: "Descartada",
};

/**
 * Tope que acepta el endpoint (`limit: int = Query(100, ge=1, le=500)`).
 *
 * Se pide el máximo en vez del defecto de 100: la cola de pendientes de un
 * producto por invitación no llega a 500 en la práctica, así que en la vista
 * que importa no hay truncado real. Cuando lo haya, se dice — ver `truncada`.
 */
const LIMITE = 500;

/** Qué mitad de la cola se está mirando. */
type Vista = "pendiente" | "historico";

async function cargarSolicitudes(query: string): Promise<SolicitudAcceso[]> {
  const res = await fetch(`/api/v1/admin/solicitudes-acceso?${query}`, {
    credentials: "include",
  });
  if (res.status === 401) throw new Error("Sesión expirada");
  if (res.status === 403) throw new Error("Requiere permisos de admin");
  if (!res.ok) throw new Error(`Error ${res.status}`);
  return res.json();
}

export function SolicitudesAccesoCard() {
  const queryClient = useQueryClient();
  const [vista, setVista] = useState<Vista>("pendiente");

  // Dos consultas y no una lista filtrada en cliente. Filtrar aquí es
  // exactamente lo que fallaba: el recorte del servidor ya se había llevado por
  // delante las pendientes viejas antes de que llegaran a este componente.
  const pendientesQuery = useQuery<SolicitudAcceso[]>({
    queryKey: ["admin-solicitudes-acceso", "pendiente"],
    queryFn: () => cargarSolicitudes(`estado=pendiente&limit=${LIMITE}`),
  });

  // El histórico sólo se pide si alguien lo abre: es la vista de consulta, no
  // la de trabajo, y no tiene por qué costar una petición a cada apertura del
  // panel.
  const historicoQuery = useQuery<SolicitudAcceso[]>({
    queryKey: ["admin-solicitudes-acceso", "historico"],
    queryFn: () => cargarSolicitudes(`limit=${LIMITE}`),
    enabled: vista === "historico",
  });

  const grantsQuery = useQuery<AccessGrant[]>({
    queryKey: ["admin-access-grants"],
    queryFn: async () => {
      const response = await fetch("/api/v1/admin/solicitudes-acceso/grants", {
        credentials: "include",
      });
      if (!response.ok) throw new Error(`Error ${response.status}`);
      return response.json() as Promise<AccessGrant[]>;
    },
  });

  const activa = vista === "pendiente" ? pendientesQuery : historicoQuery;
  const { isLoading, error } = activa;

  const cambiarEstado = useMutation({
    mutationFn: (vars: {
      id: number;
      estado: string;
      notificar?: boolean;
      conceder?: "email" | "domain";
    }) =>
      apiMutate<CambioEstado>("PATCH", `/api/v1/admin/solicitudes-acceso/${vars.id}`, {
        estado: vars.estado,
        notificar: vars.notificar ?? false,
        conceder: vars.conceder ?? null,
      }),
    onSuccess: (respuesta) => {
      queryClient.invalidateQueries({ queryKey: ["admin-solicitudes-acceso"] });
      queryClient.invalidateQueries({ queryKey: ["admin-access-grants"] });
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

  const revocar = useMutation({
    mutationFn: (grantId: number) =>
      apiMutate("DELETE", `/api/v1/admin/solicitudes-acceso/grants/${grantId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-access-grants"] });
      toast.success("Acceso revocado para nuevos inicios de sesión");
    },
    onError: () => toast.error("No se pudo revocar el acceso"),
  });

  const solicitudes = activa.data ?? [];
  // `undefined` mientras la consulta de pendientes no ha respondido: sin dato
  // no se pinta el contador, en vez de afirmar un cero que aún no se sabe.
  const pendientes = pendientesQuery.data?.length;
  // Una lista que llega justo al tope no es "N": es "al menos N". Decirlo con
  // un `+` es la diferencia entre un número y una promesa que no se sostiene.
  const truncada = solicitudes.length >= LIMITE;
  const pendientesTruncado = pendientes !== undefined && pendientes >= LIMITE;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Inbox className="h-4 w-4" aria-hidden="true" />
          Solicitudes de acceso
          {pendientes !== undefined && pendientes > 0 && (
            <Badge variant="secondary">
              {pendientes}
              {pendientesTruncado ? "+" : ""} pendientes
            </Badge>
          )}
        </CardTitle>
        <CardDescription>
          Peticiones enviadas desde la web pública. «Conceder email y avisar» activa el acceso
          antes de enviar el correo. Conceder un dominio abre el acceso a todas sus cuentas y
          debe reservarse para clientes aprobados.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {/* El conmutador, y no un filtro sobre lo ya descargado: cada vista es
            su propia consulta al servidor, que es el único sitio donde el
            recorte se puede aplicar sin perder filas por el camino. */}
        <div
          className="mb-3 flex items-center gap-1.5"
          role="group"
          aria-label="Qué solicitudes se listan"
        >
          <Button
            size="sm"
            variant={vista === "pendiente" ? "secondary" : "ghost"}
            aria-pressed={vista === "pendiente"}
            onClick={() => setVista("pendiente")}
          >
            Pendientes
          </Button>
          <Button
            size="sm"
            variant={vista === "historico" ? "secondary" : "ghost"}
            aria-pressed={vista === "historico"}
            onClick={() => setVista("historico")}
          >
            Todas
          </Button>
        </div>
        {isLoading && <Skeleton className="h-24 w-full" />}
        {error && <p className="text-destructive text-sm">{(error as Error).message}</p>}
        {!isLoading && !error && solicitudes.length === 0 && (
          <p className="text-muted-foreground text-sm">
            {vista === "pendiente"
              ? "No queda ninguna solicitud pendiente. En «Todas» está el histórico."
              : "Todavía no ha llegado ninguna solicitud."}
          </p>
        )}
        {!isLoading && !error && truncada && (
          <p className="text-muted-foreground mb-3 text-xs">
            Se muestran las {LIMITE} más recientes: hay más de las que caben en una respuesta. Usa
            «Pendientes» para no perder ninguna sin atender.
          </p>
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
                      <Button
                        size="sm"
                        disabled={cambiarEstado.isPending}
                        onClick={() =>
                          cambiarEstado.mutate({
                            id: solicitud.id,
                            estado: "atendida",
                            notificar: true,
                            conceder: "email",
                          })
                        }
                      >
                        Conceder email y avisar
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={cambiarEstado.isPending}
                        onClick={() =>
                          cambiarEstado.mutate({
                            id: solicitud.id,
                            estado: "atendida",
                            notificar: true,
                            conceder: "domain",
                          })
                        }
                      >
                        Conceder dominio
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={cambiarEstado.isPending}
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
        <div className="border-border/60 mt-5 border-t pt-4">
          <h3 className="text-sm font-semibold">Accesos dinámicos activos</h3>
          {grantsQuery.isLoading ? (
            <Skeleton className="mt-3 h-12 w-full" />
          ) : (grantsQuery.data?.length ?? 0) === 0 ? (
            <p className="text-muted-foreground mt-2 text-xs">
              No hay concesiones dinámicas; pueden seguir aplicando las variables de entorno.
            </p>
          ) : (
            <ul className="divide-border/60 mt-2 divide-y">
              {grantsQuery.data?.map((grant) => (
                <li key={grant.id} className="flex items-center justify-between gap-3 py-2">
                  <div className="min-w-0">
                    <span className="text-xs font-medium">{grant.value}</span>
                    <Badge variant="outline" className="ml-2">
                      {grant.kind === "email" ? "Email" : "Dominio"}
                    </Badge>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={revocar.isPending}
                    aria-label={`Revocar acceso de ${grant.value}`}
                    onClick={() => revocar.mutate(grant.id)}
                  >
                    Revocar
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
