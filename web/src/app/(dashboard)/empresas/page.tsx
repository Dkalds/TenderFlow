"use client";

/**
 * Empresas — el maestro canónico: quién es quién, con qué cobertura y qué queda
 * por resolver a mano.
 *
 * El estado y las llamadas viven en `_hooks/`; cada bloque de pantalla, en
 * `_components/`. Aquí queda el orden de la página y el reparto entre las dos
 * vistas del maestro.
 */

import { PanelEmpty, PanelTabs } from "@/components/console/panel";
import { SpaceShell } from "@/components/layout/space-shell";
import { useEmpresasWatchlist, useToggleEmpresaWatch } from "@/hooks/use-empresas-watchlist";
import { useEmpresasMaestro } from "./_hooks/use-empresas-maestro";
import { EmpresaPerfil } from "./_components/empresa-perfil";
import { EmpresasBuscador } from "./_components/empresas-buscador";
import { EmpresasCobertura } from "./_components/empresas-cobertura";
import { ReviewQueue } from "./_components/review-queue";

export default function EmpresasPage() {
  const maestro = useEmpresasMaestro();
  const { watchedIds } = useEmpresasWatchlist();
  const toggleWatch = useToggleEmpresaWatch();
  const { pendientes, setVista } = maestro;

  return (
    <SpaceShell spaceKey="empresas">
      <div className="space-y-6">
        <EmpresasCobertura
          stats={maestro.stats}
          vigiladas={watchedIds.size}
          onVerRevisiones={pendientes > 0 ? () => setVista("revision") : undefined}
        />

        {/* La cola de revisión deja de ser un bloque que aparece y desaparece
            según haya trabajo: es una vista con contador, así que se sabe que
            existe aunque hoy esté vacía. */}
        <PanelTabs
          label="Vistas del maestro"
          value={maestro.vista}
          onChange={setVista}
          tabs={[
            { key: "maestro" as const, label: "Maestro" },
            { key: "revision" as const, label: "Cola de revisión", badge: pendientes },
          ]}
        />

        {maestro.vista === "revision" ? (
          pendientes > 0 ? (
            <ReviewQueue />
          ) : (
            <PanelEmpty message="No hay matches dudosos pendientes de revisar." />
          )
        ) : (
          <>
            <EmpresasBuscador
              search={maestro.search}
              onSearchChange={maestro.setSearch}
              items={maestro.items}
              isLoading={maestro.isLoading}
              selectedId={maestro.selectedId}
              onSelect={maestro.setSelectedId}
              watchedIds={watchedIds}
              onToggleWatch={(empresaId, watched) =>
                toggleWatch.mutate({ empresaIds: [empresaId], watched })
              }
              toggleDisabled={toggleWatch.isPending}
            />

            {maestro.selectedId != null && <EmpresaPerfil empresaId={maestro.selectedId} />}
          </>
        )}
      </div>
    </SpaceShell>
  );
}
