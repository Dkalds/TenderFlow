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

import { Panel, PanelEmpty, PanelError, PanelTitle, Segmented } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useSolicitudesAcceso } from "../_hooks/use-solicitudes-acceso";
import type { OpcionesSolicitudesAcceso } from "../_hooks/use-solicitudes-acceso";
import { AccesosDinamicos } from "./solicitudes-acceso/accesos-dinamicos";
import { SolicitudItem } from "./solicitudes-acceso/solicitud-item";

const VISTAS = [
  { value: "pendiente", label: "Pendientes" },
  { value: "historico", label: "Todas" },
] as const;

/** Las opciones son las del hook; la app no pasa ninguna. */
export function SolicitudesAccesoCard(opciones: OpcionesSolicitudesAcceso) {
  const {
    vista,
    setVista,
    solicitudes,
    isLoading,
    error,
    reintentar,
    pendientes,
    limite,
    truncada,
    pendientesTruncado,
    grants,
    grantsLoading,
    cambiarEstado,
    revocar,
  } = useSolicitudesAcceso(opciones);

  return (
    <Panel>
      <PanelTitle
        title={
          <span className="inline-flex items-center gap-2">
            Solicitudes de acceso
            {pendientes !== undefined && pendientes > 0 && (
              <Badge variant="warning" size="sm">
                {pendientes}
                {pendientesTruncado ? "+" : ""} pendientes
              </Badge>
            )}
          </span>
        }
      />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Peticiones enviadas desde la web pública. «Conceder email y avisar» activa el acceso antes de enviar el
        correo. Conceder un dominio abre el acceso a todas sus cuentas: resérvalo para clientes aprobados.
      </p>
      {/* El conmutador, y no un filtro sobre lo ya descargado: cada vista es
          su propia consulta al servidor, que es el único sitio donde el
          recorte se puede aplicar sin perder filas por el camino. */}
      <Segmented
        aria-label="Qué solicitudes se listan"
        value={vista}
        options={VISTAS}
        onChange={setVista}
        className="mb-3"
      />
      {isLoading && <Skeleton className="h-24 w-full" />}
      {error ? (
        <PanelError
          variant="inline"
          title="No se pudieron cargar las solicitudes"
          error={error}
          onRetry={reintentar}
        />
      ) : null}
      {!isLoading && !error && solicitudes.length === 0 && (
        <PanelEmpty
          size="sm"
          title={
            vista === "pendiente"
              ? "No queda ninguna solicitud pendiente."
              : "Todavía no ha llegado ninguna solicitud."
          }
          hint={vista === "pendiente" ? "En «Todas» está el histórico." : undefined}
        />
      )}
      {!isLoading && !error && truncada && (
        <p className="text-muted-foreground mb-3 text-tf-meta">
          Se muestran las {limite} más recientes: hay más de las que caben en una respuesta. Usa «Pendientes»
          para no perder ninguna sin atender.
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
    </Panel>
  );
}
