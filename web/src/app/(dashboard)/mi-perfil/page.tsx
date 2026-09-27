"use client";

/**
 * Mi perfil — cómo se puntúan las oportunidades para este usuario.
 *
 * El estado y las llamadas viven en `_hooks/use-perfil-scoring.ts`; cada bloque
 * del formulario, en `_components/`. Aquí queda el orden de la página, el
 * esqueleto de carga y las dos acciones finales.
 *
 * El esqueleto va **dentro** de `SpaceShell` y es el mismo que pinta el
 * `loading.tsx` de la ruta: con él fuera, la cabecera del espacio aparecía, se
 * iba mientras llegaba el perfil y volvía.
 */

import { Button } from "@/components/ui/button";
import { SpaceShell } from "@/components/layout/space-shell";
import { formatDateTime } from "@/lib/utils";
import { usePerfilScoring } from "./_hooks/use-perfil-scoring";
import { AmbitoPerfilCard } from "./_components/ambito-perfil-card";
import { CpvsInteresCard, KeywordsAfinidadCard } from "./_components/afinidad-cards";
import { GdprSection } from "./_components/gdpr-section";
import { PerfilEsqueleto } from "./_components/perfil-esqueleto";
import { InformeSemanalCard } from "./_components/informe-semanal-card";
import { PesosPropuestosCard } from "./_components/pesos-propuestos-card";
import { PesosScoringCard } from "./_components/pesos-scoring-card";
import { RangoImporteCard } from "./_components/rango-importe-card";
import { TecnologiasOrganizacionCard } from "./_components/tecnologias-organizacion-card";

export default function MiPerfilPage() {
  const perfil = usePerfilScoring();
  const { data, saveMut, deleteMut } = perfil;

  if (perfil.isLoading) {
    return (
      <SpaceShell spaceKey="mi-perfil">
        <PerfilEsqueleto />
      </SpaceShell>
    );
  }

  return (
    <SpaceShell spaceKey="mi-perfil">
      <div className="max-w-2xl space-y-6">
        <div>
          <p className="text-tf-meta text-muted-foreground">
            Personaliza cómo se puntúan las oportunidades. Los cambios se aplican en el Radar, en el detalle de
            cada licitación y en los rankings de análisis.
          </p>
          {perfil.hasProfile && (
            <p className="mt-1 text-tf-meta text-muted-foreground">
              Última actualización: {data?.updated_at ? formatDateTime(data.updated_at) : "—"}
            </p>
          )}
        </div>

        <AmbitoPerfilCard
          inherited={data?.inherited === true}
          shared={perfil.sharedWithOrganization}
          onSharedChange={perfil.setSharedWithOrganization}
        />

        <TecnologiasOrganizacionCard />

        {/* Debajo de las tecnologías por ser el otro ajuste de organización
            de esta página, y no al final: nace apagado, así que tiene que
            verse para que alguien lo encienda. */}
        <InformeSemanalCard />

        <PesosScoringCard
          weights={perfil.weights}
          total={perfil.total}
          weightsValid={perfil.weightsValid}
          onWeightChange={perfil.handleWeightChange}
          onReset={perfil.handleResetWeights}
        />

        {/* Pegada a los sliders que propone cambiar: leerla en otro sitio
            obligaría a recordar los seis números de arriba. */}
        <PesosPropuestosCard />

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
          error={perfil.errores.cpvs}
        />

        <RangoImporteCard
          importeMin={perfil.importeMin}
          importeMax={perfil.importeMax}
          onImporteMinChange={perfil.setImporteMin}
          onImporteMaxChange={perfil.setImporteMax}
          errores={perfil.errores}
        />

        <GdprSection />

        {/* Acciones */}
        <div className="flex items-center gap-3 pb-6">
          <Button onClick={perfil.guardar} disabled={!perfil.dirty || !perfil.weightsValid || saveMut.isPending}>
            {saveMut.isPending ? "Guardando…" : "Guardar perfil"}
          </Button>
          {perfil.hasProfile && !data?.inherited && (
            <Button
              variant="outline"
              onClick={() => deleteMut.mutate()}
              disabled={deleteMut.isPending}
              className="text-destructive hover:bg-destructive/10"
            >
              {deleteMut.isPending ? "Eliminando…" : "Eliminar perfil"}
            </Button>
          )}
          {perfil.dirty && !perfil.weightsValid && (
            <p className="text-tf-meta text-destructive">Los pesos deben sumar 100 para guardar.</p>
          )}
        </div>
      </div>
    </SpaceShell>
  );
}
