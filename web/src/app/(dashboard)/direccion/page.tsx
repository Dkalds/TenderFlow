"use client";

/**
 * F4.2 — Dirección: resultados, carga y actividad del equipo.
 *
 * El Embudo son tres barras y cuatro cifras. Con eso un propietario no puede
 * responder ninguna de las preguntas que se hace: dónde ganamos, dónde
 * perdemos, cuánto tarda el ciclo, si vamos mejor o peor y quién tiene qué
 * encima de la mesa. El embudo vive en Oportunidades → Rendimiento (por
 * cohorte de altas); Dirección mira los **cierres** de un periodo frente al
 * mismo periodo de hace un año.
 *
 * Tres vistas, en `?vista=` como el resto de espacios:
 * - **Resultado** (`_components/resultado-view.tsx`): cifras con su periodo
 *   anterior, previsión, pérdidas, cortes, Radar y lo que falta registrar.
 * - **Carga del equipo** (`_components/carga-equipo.tsx`).
 * - **Actividad del equipo**, el mismo feed que Equipo → Actividad.
 *
 * Cada vista pide sólo lo suyo. Antes la página pedía el cuadro entero también
 * para la pestaña de actividad, la tenía esperando a esa consulta —la más
 * pesada del espacio— y, si fallaba, la actividad tampoco se veía.
 *
 * La regla de la pantalla: **ninguna cifra se publica por debajo del mínimo**.
 * El backend devuelve `valor: null` con su `n`, y aquí se enseña el hueco con
 * el motivo. Una tasa de éxito del 100 % sobre dos cierres, en la pantalla que
 * mira dirección, es peor que un hueco: el hueco se pregunta, el número se cree.
 */
import dynamic from "next/dynamic";

import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { Skeleton } from "@/components/ui/skeleton";
import { useActiveOrganizationId, useRolActivo } from "@/hooks/use-organization";
import { CONSOLE_SPACES } from "@/lib/console-spaces";
import { ResultadoView } from "./_components/resultado-view";
import { SinPermisoDireccion } from "./_components/sin-permiso";

// Sólo Resultado se ve al entrar. Carga y Actividad viajan aparte, como las
// pestañas secundarias de Equipo: la ruta tiene un techo de First Load JS
// (`web/bundle-budget.json`) y la tabla, el selector y el feed no hacen falta
// para la primera pantalla.
const loading = () => <Skeleton className="h-80 w-full rounded-xl" />;
const CargaEquipoView = dynamic(
  () => import("./_components/carga-equipo").then((modulo) => modulo.CargaEquipoView),
  { loading },
);
const ActividadEquipo = dynamic(
  () => import("./_components/actividad-equipo").then((modulo) => modulo.ActividadEquipo),
  { loading },
);

const SPACE = CONSOLE_SPACES.find((space) => space.key === "direccion")!;

/** Roles que abren Dirección. El permiso lo impone la API; esto evita pedir lo que va a dar 403. */
const ROLES_DIRECCION = new Set(["owner", "admin"]);

export default function DireccionPage() {
  const { view: vista, setView: setVista } = useSpaceView(SPACE);
  // Sin `organization_id` el backend resuelve la organización **personal**, y
  // las oportunidades viven en la del equipo: cada vista la manda.
  const organizationId = useActiveOrganizationId();
  // Con el rol ya conocido, un `member` no lanza consultas que van a dar 403:
  // ve el aviso en las tres vistas. Mientras no se sabe, las vistas piden y el
  // 403 del backend dice lo mismo.
  const rol = useRolActivo();
  const sinPermiso = rol !== undefined && !ROLES_DIRECCION.has(rol);

  return (
    <SpaceShell spaceKey="direccion" view={vista} onViewChange={setVista}>
      {sinPermiso ? (
        <SinPermisoDireccion />
      ) : vista === "actividad" ? (
        <ActividadEquipo organizationId={organizationId} />
      ) : vista === "carga" ? (
        <CargaEquipoView organizationId={organizationId} />
      ) : (
        <ResultadoView organizationId={organizationId} />
      )}
    </SpaceShell>
  );
}
