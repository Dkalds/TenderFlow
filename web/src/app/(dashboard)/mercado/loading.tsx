import { SpaceShellEsqueleto, VistaEsqueleto } from "@/components/layout/space-shell-esqueleto";

/**
 * Esqueleto de ruta de Mercado: el marco del espacio con una pestaña por vista
 * y, dentro, el mismo esqueleto que pinta cada vista mientras llega su chunk. El
 * relevo ruta → página → vista no mueve nada: primero aparece la cabecera real
 * y después la vista, en el sitio de su esqueleto.
 *
 * Caía en el genérico de `(dashboard)/loading.tsx` —un título y cuatro
 * tarjetas de KPI—, que no es la forma de ningún corte de Mercado.
 */
export default function MercadoLoading() {
  return (
    <SpaceShellEsqueleto spaceKey="mercado">
      <VistaEsqueleto />
    </SpaceShellEsqueleto>
  );
}
