"use client";

/**
 * Mi perfil de scoring — cómo se puntúan las oportunidades para este usuario.
 *
 * El estado y las llamadas viven en `_hooks/use-perfil-scoring.ts`; cada bloque
 * del formulario, en `_components/`. Aquí queda el orden de la página, el
 * esqueleto de carga y las dos acciones finales.
 */

import { Save, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SpaceShell } from "@/components/layout/space-shell";
import { formatDateTime } from "@/lib/utils";
import { usePerfilScoring } from "./_hooks/use-perfil-scoring";
import { AmbitoPerfilCard } from "./_components/ambito-perfil-card";
import { CpvsInteresCard, KeywordsAfinidadCard } from "./_components/afinidad-cards";
import { GdprSection } from "./_components/gdpr-section";
import { PesosScoringCard } from "./_components/pesos-scoring-card";
import { RangoImporteCard } from "./_components/rango-importe-card";
import { TecnologiasOrganizacionCard } from "./_components/tecnologias-organizacion-card";

export default function MiPerfilPage() {
  const perfil = usePerfilScoring();
  const { data, saveMut, deleteMut } = perfil;

  if (perfil.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  return (
    <SpaceShell spaceKey="mi-perfil">
      <div className="max-w-2xl space-y-6">
        <div>
          <h1 className="sr-only">Mi perfil de scoring</h1>
          <p className="text-muted-foreground mt-1">
            Personaliza cómo se puntúan las oportunidades. Los cambios aplican en el panel de
            detalle, el Radar y los rankings analíticos.
          </p>
          {perfil.hasProfile && (
            <p className="mt-2 text-xs text-muted-foreground">
              Última actualización:{" "}
              {data?.updated_at ? formatDateTime(data.updated_at) : "—"}
            </p>
          )}
        </div>

        <AmbitoPerfilCard
          inherited={data?.inherited === true}
          shared={perfil.sharedWithOrganization}
          onSharedChange={perfil.setSharedWithOrganization}
        />

        <TecnologiasOrganizacionCard />

        <PesosScoringCard
          weights={perfil.weights}
          total={perfil.total}
          weightsValid={perfil.weightsValid}
          onWeightChange={perfil.handleWeightChange}
          onReset={perfil.handleResetWeights}
        />

        <KeywordsAfinidadCard
          keywords={perfil.keywords}
          kwInput={perfil.kwInput}
          onKwInputChange={perfil.setKwInput}
          onAdd={perfil.addKeyword}
          onRemove={perfil.removeKeyword}
        />

        <CpvsInteresCard
          cpvs={perfil.cpvs}
          cpvInput={perfil.cpvInput}
          onCpvInputChange={perfil.setCpvInput}
          onAdd={perfil.addCpv}
          onRemove={perfil.removeCpv}
        />

        <RangoImporteCard
          importeMin={perfil.importeMin}
          importeMax={perfil.importeMax}
          onImporteMinChange={perfil.setImporteMin}
          onImporteMaxChange={perfil.setImporteMax}
        />

        <GdprSection />

        {/* Acciones */}
        <div className="flex items-center gap-3 pb-6">
          <Button
            onClick={() => saveMut.mutate()}
            disabled={!perfil.dirty || !perfil.weightsValid || saveMut.isPending}
            className="gap-1.5"
          >
            <Save className="h-4 w-4" />
            {saveMut.isPending ? "Guardando…" : "Guardar perfil"}
          </Button>
          {perfil.hasProfile && !data?.inherited && (
            <Button
              variant="outline"
              onClick={() => deleteMut.mutate()}
              disabled={deleteMut.isPending}
              className="gap-1.5 text-destructive hover:bg-destructive/10"
            >
              <Trash2 className="h-4 w-4" />
              {deleteMut.isPending ? "Eliminando…" : "Eliminar perfil"}
            </Button>
          )}
          {perfil.dirty && !perfil.weightsValid && (
            <p className="text-sm text-destructive">Los pesos deben sumar 100 para guardar.</p>
          )}
        </div>
      </div>
    </SpaceShell>
  );
}
