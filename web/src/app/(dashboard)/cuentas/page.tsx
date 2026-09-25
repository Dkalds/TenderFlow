"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Building2, Plus } from "lucide-react";

import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { CONSOLE_SPACES } from "@/lib/console-spaces";
import { usePuedeEscribir, useRolActivo } from "@/hooks/use-organization";

import { ListaCuentas } from "./_components/lista-cuentas";
import { NuevaCuentaDialog } from "./_components/nueva-cuenta-dialog";

/**
 * F1.5 — Cuentas objetivo.
 *
 * `Mercado → Órganos` era un corte analítico sin acción: enseñaba cuánto
 * licita un órgano y no dejaba hacer nada al respecto. Este espacio añade lo
 * que faltaba: seguir a un cliente —con todos sus órganos de contratación— y
 * ver qué pasa con él y qué tiene el equipo con él, en la lista y en la ficha
 * de cada cuenta (`/cuentas/[id]`).
 *
 * La pestaña «Todos los órganos» (`?vista=mercado`) **no** incrusta aquella
 * vista: enlaza a ella, que sigue viviendo en Mercado con todos sus filtros. Lo
 * que une las dos pantallas es la acción: el botón «Seguir» del panel de órgano
 * de Mercado crea o completa una cuenta de esta lista (`useSeguimiento` enruta
 * los órganos a `/cuentas`).
 *
 * Todo el estado es del servidor y de la **organización activa**. La API
 * decide el permiso —un `viewer` recibe 403—, y la pantalla además le esconde
 * lo que no puede hacer, en vez de ofrecerle botones que siempre fallan.
 */

const SPACE = CONSOLE_SPACES.find((space) => space.key === "cuentas")!;

export default function CuentasPage() {
  // `useSpaceView` y no estado local: la vista vive en `?vista=`, que es lo
  // que hace que el corte sea enlazable y sobreviva a un refresco. Con
  // `useState` el deep-link que documenta `space-views.ts` aterrizaba
  // siempre en la primera vista y la URL nunca cambiaba.
  const { view: vista, setView: setVista } = useSpaceView(SPACE);
  const router = useRouter();
  const puedeEscribir = usePuedeEscribir();
  const soloLectura = useRolActivo() === "viewer";
  const [creando, setCreando] = React.useState(false);

  return (
    <SpaceShell
      spaceKey="cuentas"
      view={vista}
      onViewChange={setVista}
      actions={
        vista !== "mercado" && puedeEscribir ? (
          <Button size="sm" onClick={() => setCreando(true)}>
            <Plus aria-hidden="true" />
            Nueva cuenta
          </Button>
        ) : undefined
      }
    >
      {vista === "mercado" ? (
        // Un enlace y no una copia de la vista: el ranking de órganos, con sus
        // filtros de ámbito, es de Mercado. Hasta 2026-09-25 esto era un vacío
        // que remitía a Mercado sin forma de llegar.
        <EmptyState
          icon={Building2}
          title="El análisis de órganos vive en Mercado"
          hint="Mercado → Órganos es el corte analítico completo. Sigue un órgano desde su panel y aparecerá aquí, en las cuentas de tu organización."
          actionLabel="Abrir Mercado → Órganos"
          onAction={() => router.push("/mercado?vista=organos")}
        />
      ) : (
        <div className="flex flex-col gap-4">
          {soloLectura && (
            <p className="text-xs text-muted-foreground">
              Tu rol en esta organización es de solo lectura: ves las cuentas del equipo, pero no
              puedes crearlas ni cambiarlas.
            </p>
          )}
          <ListaCuentas
            puedeEscribir={puedeEscribir}
            onNueva={puedeEscribir ? () => setCreando(true) : undefined}
          />
        </div>
      )}
      <NuevaCuentaDialog open={creando} onOpenChange={setCreando} />
    </SpaceShell>
  );
}
