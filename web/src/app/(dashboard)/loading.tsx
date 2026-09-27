import { SpaceShellEsqueleto, VistaEsqueleto } from "@/components/layout/space-shell-esqueleto";

/**
 * Esqueleto genérico del dashboard, para los espacios sin `loading.tsx` propio.
 *
 * Tenía la forma de una plantilla de dashboard —un título de 32 px, cuatro
 * tarjetas KPI y dos gráficos, pegados al borde— que no se parecía a ninguna
 * pantalla: al llegar la página todo saltaba. Ahora es la cabecera de
 * `SpaceShell` (h-11, título a 15 px) y el cuerpo con su relleno, las mismas
 * cotas que la pantalla real. Sin pestañas: aquí no se sabe de qué espacio es.
 */
export default function DashboardLoading() {
  return (
    <SpaceShellEsqueleto spaceKey="">
      <VistaEsqueleto />
    </SpaceShellEsqueleto>
  );
}
