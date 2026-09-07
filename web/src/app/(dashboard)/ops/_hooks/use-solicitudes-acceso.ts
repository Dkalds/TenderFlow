"use client";

/**
 * Cola de solicitudes de acceso: las dos consultas, la de concesiones y las dos
 * mutaciones que las mueven.
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
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { adminKeys } from "@/lib/query-keys";

export interface SolicitudAcceso {
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

export interface AccessGrant {
  id: number;
  kind: "email" | "domain";
  value: string;
  active: boolean;
}

/**
 * Tope que acepta el endpoint (`limit: int = Query(100, ge=1, le=500)`).
 *
 * Se pide el máximo en vez del defecto de 100: la cola de pendientes de un
 * producto por invitación no llega a 500 en la práctica, así que en la vista
 * que importa no hay truncado real. Cuando lo haya, se dice — ver `truncada`.
 */
export const LIMITE = 500;

/** Qué mitad de la cola se está mirando. */
export type Vista = "pendiente" | "historico";

export interface CambioEstadoVars {
  id: number;
  estado: string;
  notificar?: boolean;
  conceder?: "email" | "domain";
}

async function cargarSolicitudes(query: string): Promise<SolicitudAcceso[]> {
  return fetchWithAuth<SolicitudAcceso[]>(`/api/v1/admin/solicitudes-acceso?${query}`);
}

export function useSolicitudesAcceso() {
  const queryClient = useQueryClient();
  const [vista, setVista] = useState<Vista>("pendiente");

  // Dos consultas y no una lista filtrada en cliente. Filtrar aquí es
  // exactamente lo que fallaba: el recorte del servidor ya se había llevado por
  // delante las pendientes viejas antes de que llegaran a este componente.
  const pendientesQuery = useQuery<SolicitudAcceso[]>({
    queryKey: adminKeys.solicitudes.vista("pendiente"),
    queryFn: () => cargarSolicitudes(`estado=pendiente&limit=${LIMITE}`),
  });

  // El histórico sólo se pide si alguien lo abre: es la vista de consulta, no
  // la de trabajo, y no tiene por qué costar una petición a cada apertura del
  // panel.
  const historicoQuery = useQuery<SolicitudAcceso[]>({
    queryKey: adminKeys.solicitudes.vista("historico"),
    queryFn: () => cargarSolicitudes(`limit=${LIMITE}`),
    enabled: vista === "historico",
  });

  const grantsQuery = useQuery<AccessGrant[]>({
    queryKey: adminKeys.accessGrants,
    queryFn: () => fetchWithAuth<AccessGrant[]>("/api/v1/admin/solicitudes-acceso/grants"),
  });

  const activa = vista === "pendiente" ? pendientesQuery : historicoQuery;

  const cambiarEstado = useMutation({
    mutationFn: (vars: CambioEstadoVars) =>
      apiMutate<CambioEstado>("PATCH", `/api/v1/admin/solicitudes-acceso/${vars.id}`, {
        estado: vars.estado,
        notificar: vars.notificar ?? false,
        conceder: vars.conceder ?? null,
      }),
    onSuccess: (respuesta) => {
      queryClient.invalidateQueries({ queryKey: adminKeys.solicitudes.all });
      queryClient.invalidateQueries({ queryKey: adminKeys.accessGrants });
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
      queryClient.invalidateQueries({ queryKey: adminKeys.accessGrants });
      toast.success("Acceso revocado para nuevos inicios de sesión");
    },
    onError: () => toast.error("No se pudo revocar el acceso"),
  });

  const solicitudes = activa.data ?? [];
  // `undefined` mientras la consulta de pendientes no ha respondido: sin dato
  // no se pinta el contador, en vez de afirmar un cero que aún no se sabe.
  const pendientes = pendientesQuery.data?.length;

  return {
    vista,
    setVista,
    solicitudes,
    isLoading: activa.isLoading,
    error: activa.error,
    pendientes,
    // Una lista que llega justo al tope no es "N": es "al menos N". Decirlo con
    // un `+` es la diferencia entre un número y una promesa que no se sostiene.
    truncada: solicitudes.length >= LIMITE,
    pendientesTruncado: pendientes !== undefined && pendientes >= LIMITE,
    grants: grantsQuery.data,
    grantsLoading: grantsQuery.isLoading,
    cambiarEstado,
    revocar,
  };
}
