"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useTheme } from "next-themes";
import { AlignJustify, LayoutGrid, LogOut, Moon, Sun } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { type MontajeDiferido, useMontajeDiferido } from "@/components/ui/carga-diferida";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DisparadorCuenta } from "@/components/layout/menus-diferidos";
import { apiMutate } from "@/lib/api-client";
import { useDensity } from "@/lib/density";
import { ICONO_ESPACIO } from "@/lib/iconos";
import { reportError } from "@/lib/report-error";

// El selector de organización solo existe con el menú abierto: llega al
// abrirlo. Su hueco mide lo mismo que su disparador para que el menú no salte.
const SelectorOrganizacion = dynamic(
  () => import("@/components/layout/selector-organizacion").then((modulo) => modulo.SelectorOrganizacion),
  { ssr: false, loading: () => <Skeleton className="h-8 w-full" /> },
);

const IconoEquipo = ICONO_ESPACIO.equipo;

/**
 * Menú de cuenta del rail: lo que vivía en el extremo derecho del TopNav.
 * El rail lo monta diferido (`menus-diferidos.tsx`).
 */
export function MenuCuenta(montaje: MontajeDiferido) {
  // `resolvedTheme`, no `theme`: con `defaultTheme="system"` el valor de
  // `theme` es "system" hasta que el usuario elige, y este toggle decide el
  // siguiente tema a partir del que se está viendo de verdad.
  const { resolvedTheme, setTheme } = useTheme();
  const { compact, toggleCompact } = useDensity();
  const { disparador, abiertoAlMontar } = useMontajeDiferido(montaje);

  const handleLogout = async () => {
    try {
      await apiMutate("POST", "/api/v1/auth/logout");
    } catch (err) {
      reportError("ConsoleRail.logout", err);
    }
    // Recarga completa a propósito: tira la caché de React Query de la sesión
    // que se cierra y el `SessionProvider` arranca sin cookie.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- frontera de sesión, ver arriba
    window.location.href = "/login";
  };

  return (
    <DropdownMenu defaultOpen={abiertoAlMontar}>
      <DropdownMenuTrigger asChild>
        <DisparadorCuenta ref={disparador} />
      </DropdownMenuTrigger>
      <DropdownMenuContent side="right" align="end" className="w-60">
        <p className="px-2 pt-1 pb-1.5 text-tf-micro font-medium text-muted-foreground">Organización activa</p>
        <div className="px-2 pb-2">
          <SelectorOrganizacion />
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/equipo">
            <IconoEquipo className="h-4 w-4" aria-hidden="true" />
            Gestionar equipo
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={(event) => {
            event.preventDefault();
            toggleCompact();
          }}
        >
          {compact ? (
            <LayoutGrid className="h-4 w-4" aria-hidden="true" />
          ) : (
            <AlignJustify className="h-4 w-4" aria-hidden="true" />
          )}
          {compact ? "Densidad cómoda" : "Densidad compacta"}
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={(event) => {
            event.preventDefault();
            setTheme(resolvedTheme === "dark" ? "light" : "dark");
          }}
        >
          {resolvedTheme === "dark" ? (
            <Sun className="h-4 w-4" aria-hidden="true" />
          ) : (
            <Moon className="h-4 w-4" aria-hidden="true" />
          )}
          {resolvedTheme === "dark" ? "Modo claro" : "Modo oscuro"}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => handleLogout()} className="text-destructive focus:text-destructive">
          <LogOut className="h-4 w-4" aria-hidden="true" />
          Cerrar sesión
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
