"use client";

import { usePathname } from "next/navigation";
import { ProfileSkeleton } from "@/components/competitors/company-profile-esqueleto";
import { SpaceShellEsqueleto, VistaEsqueleto } from "@/components/layout/space-shell-esqueleto";

/**
 * Esqueleto de ruta de Competencia.
 *
 * Es de cliente porque este `loading.tsx` envuelve también la ficha de empresa
 * (`/competencia/empresa/[empresaId]`), y el prefetch de un enlace desde otro
 * espacio —el adjudicatario de una cuenta, un socio de UTE— se para aquí. Con
 * el marco de pestañas para todo, abrir una empresa enseñaría el espacio antes
 * que la ficha. Por eso mira la ruta: la del espacio pinta su marco con la
 * vista, y cualquier hija la forma de la ficha, la misma que pinta
 * `CompanyProfile` mientras llega su dato.
 *
 * Caía en el genérico de `(dashboard)/loading.tsx` —un título y cuatro
 * tarjetas de KPI—, que no es la forma de ninguna de las dos.
 */
export default function CompetenciaLoading() {
  const pathname = usePathname();
  if (pathname !== "/competencia") return <ProfileSkeleton />;
  return (
    <SpaceShellEsqueleto spaceKey="competencia">
      <VistaEsqueleto />
    </SpaceShellEsqueleto>
  );
}
