"use client";

import { usePathname } from "next/navigation";
import { SpaceShellEsqueleto } from "@/components/layout/space-shell-esqueleto";
import { FichaEsqueleto } from "./[id]/_components/ficha-esqueleto";
import { TableroEsqueleto } from "./_components/tablero-esqueleto";

/**
 * Esqueleto de ruta de Oportunidades.
 *
 * Es cliente, y no por capricho: un `loading.tsx` envuelve la página **y los
 * segmentos hijos**, así que este es también el que se ve al abrir una ficha
 * (`/oportunidades/123`) desde otro espacio —el prefetch de un `<Link>` desde
 * la Agenda o Dirección se detiene en el primer `loading.tsx` que encuentra, y
 * es este—. Con la forma del tablero para todo, abrir una oportunidad enseñaba
 * un tablero antes de la ficha. Por eso mira la ruta: la del espacio pinta el
 * tablero, que es la vista de entrada, y cualquier hija el de la ficha.
 */
export default function OportunidadesLoading() {
  const pathname = usePathname();
  if (pathname !== "/oportunidades") return <FichaEsqueleto />;
  return (
    <SpaceShellEsqueleto spaceKey="oportunidades" bleed>
      <TableroEsqueleto />
    </SpaceShellEsqueleto>
  );
}
