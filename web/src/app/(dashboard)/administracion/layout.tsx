import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Administración",
};

// La guarda de administrador ya no vive aquí: se movió a
// `ops/_components/administracion-view.tsx` para que también la imponga
// `/ops?vista=administracion`, que monta el mismo cuerpo sin pasar por este
// layout. El layout se queda sólo con el título de la pestaña.
export default function AdministracionLayout({ children }: { children: React.ReactNode }) {
  return children;
}
