import { SpaceShellEsqueleto } from "@/components/layout/space-shell-esqueleto";
import { PerfilEsqueleto } from "./_components/perfil-esqueleto";

/**
 * Esqueleto de ruta de Mi perfil: la cabecera del espacio y la misma columna
 * que pinta la página mientras llega el perfil (`PerfilEsqueleto`), así que el
 * relevo ruta → página no mueve nada.
 */
export default function MiPerfilLoading() {
  return (
    <SpaceShellEsqueleto spaceKey="mi-perfil">
      <PerfilEsqueleto />
    </SpaceShellEsqueleto>
  );
}
