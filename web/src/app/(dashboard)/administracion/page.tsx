import AdministracionView from "../ops/_components/administracion-view";

/**
 * Boundary de ruta. El cuerpo vive en `ops/_components/administracion-view`
 * porque el espacio Ops monta la misma vista bajo `?vista=administracion`.
 * La guarda de administrador va dentro de esa vista, no en el layout, para que
 * la impongan las dos entradas por igual.
 */
export default function AdministracionPage() {
  return <AdministracionView />;
}
