"use client";

import { usePathname } from "next/navigation";
import { SpaceShellEsqueleto } from "@/components/layout/space-shell-esqueleto";
import { FichaCuentaEsqueleto } from "./[id]/_components/ficha-esqueleto";
import { ListaCuentasEsqueleto } from "./_components/lista-cuentas-esqueleto";

/**
 * Esqueleto de ruta de Cuentas.
 *
 * Es de cliente por la misma razón que el de Oportunidades: este `loading.tsx`
 * envuelve también la ficha (`/cuentas/[id]`), y el prefetch de un enlace a una
 * cuenta desde otro espacio se detiene en él. En el espacio pinta su marco con
 * la lista; en una ficha, la forma de la ficha.
 */
export default function CuentasLoading() {
  const pathname = usePathname();
  if (pathname !== "/cuentas") return <FichaCuentaEsqueleto />;
  return (
    <SpaceShellEsqueleto spaceKey="cuentas">
      <ListaCuentasEsqueleto />
    </SpaceShellEsqueleto>
  );
}
