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
 * Los datos y las dos mutaciones están en `_hooks/use-solicitudes-acceso.ts`,
 * con la explicación de por qué son dos consultas y no una lista filtrada en
 * cliente. Aquí queda la composición: el conmutador de vista, los estados de
 * carga/vacío/error y las dos listas.
 *
 * Vive en su propio fichero y no dentro de `administracion-view.tsx`, que ya
 * pasa de 800 líneas y está en el roadmap de descomposición del UX_AUDIT.
 */

import { Inbox } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { LIMITE, useSolicitudesAcceso } from "../_hooks/use-solicitudes-acceso";
import { AccesosDinamicos } from "./solicitudes-acceso/accesos-dinamicos";
import { SolicitudItem } from "./solicitudes-acceso/solicitud-item";

export function SolicitudesAccesoCard() {
  const {
    vista,
    setVista,
    solicitudes,
    isLoading,
    error,
    pendientes,
    truncada,
    pendientesTruncado,
    grants,
    grantsLoading,
    cambiarEstado,
    revocar,
  } = useSolicitudesAcceso();

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
              <SolicitudItem
                key={solicitud.id}
                solicitud={solicitud}
                ocupado={cambiarEstado.isPending}
                onCambiarEstado={cambiarEstado.mutate}
              />
            ))}
          </ul>
        )}
        <AccesosDinamicos
          grants={grants}
          isLoading={grantsLoading}
          revocando={revocar.isPending}
          onRevocar={revocar.mutate}
        />
      </CardContent>
    </Card>
  );
}
