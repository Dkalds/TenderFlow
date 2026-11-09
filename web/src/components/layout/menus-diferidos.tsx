"use client";

import { Bookmark, Download } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Diferido } from "@/components/ui/carga-diferida";
import {
  CLASE_DISPARADOR_CAMPANA,
  ContenidoDisparadorCampana,
  etiquetaCampana,
  REFRESCO_CAMPANA_MS,
} from "@/components/campana/disparador";
import { useAvisos } from "@/components/campana/avisos";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import { ICONO_ENTIDAD } from "@/lib/iconos";
import { useUiStore } from "@/lib/ui-store";

/**
 * Los menús del marco, con Radix fuera del First Load (`ui/carga-diferida.tsx`):
 * menú de cuenta, exportar, campana y vistas guardadas. Cada uno pinta su
 * disparador provisional —el mismo botón que el real, con su nombre accesible
 * y su `aria-haspopup`— hasta que llega el módulo con Radix.
 *
 * Los `cargar` viven fuera de los componentes: `Diferido` los usa como
 * dependencia de un efecto y tienen que ser estables.
 */

const IconoCuenta = ICONO_ENTIDAD.persona;

/**
 * El botón del menú de cuenta. Neutro: el naranja es de la acción y del
 * destino activo, no de un avatar que está siempre ahí. Acepta `ref` y el resto
 * de props: el real lo envuelve en un `DropdownMenuTrigger asChild`.
 */
export function DisparadorCuenta(props: React.ComponentProps<"button">) {
  return (
    <button
      type="button"
      aria-label="Menú de cuenta"
      aria-haspopup="menu"
      aria-expanded={false}
      className="tf-pressable grid h-8 w-8 place-items-center rounded-full border border-divider bg-secondary text-muted-foreground hover:text-foreground"
      {...props}
    >
      <IconoCuenta className="h-4 w-4" aria-hidden="true" />
    </button>
  );
}

const cargarCuenta = () => import("@/components/layout/menu-cuenta").then((modulo) => modulo.MenuCuenta);

export function MenuCuentaDiferido() {
  return (
    <Diferido
      cargar={cargarCuenta}
      props={{}}
      abreCon="pulsar"
      disparador={(eventos) => <DisparadorCuenta data-state="closed" {...eventos} />}
    />
  );
}

const cargarExportar = () => import("@/components/export-popover").then((modulo) => modulo.ExportPopover);

/** «Exportar» de la barra de ámbito (`ExportPopover`), con la talla de la consola. */
export function ExportarDiferido({ label = "Exportar" }: { label?: string }) {
  return (
    <Diferido
      cargar={cargarExportar}
      props={{ label }}
      abreCon="pulsar"
      disparador={(eventos) => (
        <button
          type="button"
          aria-haspopup="menu"
          aria-expanded={false}
          data-state="closed"
          className={buttonVariants({ variant: "outline", size: "sm" })}
          {...eventos}
        >
          <Download aria-hidden="true" />
          {label}
        </button>
      )}
    />
  );
}

const cargarCampana = () => import("@/components/notification-bell").then((modulo) => modulo.NotificationBell);

/**
 * La campana (`NotificationBell`). El provisional ya enseña el recuento: pide
 * los avisos con la misma clave y el mismo refresco que la real, así que al
 * llegar ésta no hay una segunda petición.
 */
export function CampanaDiferida() {
  const organizationId = useActiveOrganizationId();
  const sinLeer = useAvisos(organizationId, { refetchInterval: REFRESCO_CAMPANA_MS }).data?.sin_leer ?? 0;
  return (
    <Diferido
      cargar={cargarCampana}
      props={{}}
      abreCon="pulsar"
      disparador={(eventos) => (
        <button
          type="button"
          aria-label={etiquetaCampana(sinLeer)}
          aria-haspopup="menu"
          aria-expanded={false}
          data-state="closed"
          className={CLASE_DISPARADOR_CAMPANA}
          {...eventos}
        >
          <ContenidoDisparadorCampana sinLeer={sinLeer} />
        </button>
      )}
    />
  );
}

const cargarVistas = () => import("@/components/saved-views-menu").then((modulo) => modulo.SavedViewsMenu);

/**
 * Las vistas guardadas (`SavedViewsMenu`). La paleta también las abre
 * (`openSavedViews`): si lo hace antes de que lleguen, se montan ya y se
 * abren solas, porque su estado de apertura vive en el store.
 */
export function VistasDiferidas() {
  const abiertas = useUiStore((s) => s.savedViewsOpen);
  return (
    <Diferido
      cargar={cargarVistas}
      props={{}}
      abreCon="clic"
      montarYa={abiertas}
      disparador={(eventos) => (
        <Button variant="ghost" size="sm" aria-haspopup="dialog" aria-expanded={false} data-state="closed" {...eventos}>
          <Bookmark className="text-primary" aria-hidden="true" />
          Vistas
        </Button>
      )}
    />
  );
}
