import ProyectosModulosView from "../mercado/_components/proyectos-modulos-view";

/**
 * Boundary de ruta. El cuerpo vive en
 * `mercado/_components/proyectos-modulos-view` porque el espacio Mercado monta
 * la misma vista bajo `?vista=proyectos`.
 */
export default function ProyectosModulosPage() {
  return <ProyectosModulosView />;
}
