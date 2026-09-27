import { SpaceShellEsqueleto, VistaEsqueleto } from "@/components/layout/space-shell-esqueleto";

/**
 * Esqueleto de ruta de la Agenda: el marco del espacio y, dentro, el mismo
 * bloque que pinta la página mientras llega el chunk de la vista
 * (`VistaEsqueleto`, el `loading` de `page.tsx`). Así el relevo ruta → página →
 * vista no mueve nada.
 *
 * Caía en el genérico de `(dashboard)/loading.tsx`, que no es la forma de la
 * Agenda. No hay rutas hijas, así que no hace falta mirar la ruta (como sí
 * hace el de Oportunidades con su ficha).
 */
export default function MiPipelineLoading() {
  return (
    <SpaceShellEsqueleto spaceKey="mi-pipeline">
      <VistaEsqueleto />
    </SpaceShellEsqueleto>
  );
}
