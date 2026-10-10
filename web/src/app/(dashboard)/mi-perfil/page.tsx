"use client";

/**
 * Mi perfil — cómo se puntúan las oportunidades para este usuario.
 *
 * El estado y las llamadas viven en `_hooks/use-perfil-scoring.ts`; cada bloque
 * del formulario, en `_components/`. Aquí queda el orden de la página: primero
 * qué te interesa, después cuánto pesa cada criterio —el orden en que lo
 * promete el menú—, y al lado, cómo quedaría el Radar con lo que hay en
 * pantalla.
 *
 * Solo hay un formulario y una barra de guardado. Los ajustes de la
 * organización (tecnologías, informe semanal) están en Equipo › Organización y
 * los datos de la cuenta, en Ajustes: cada uno guardaba por su lado y esta
 * página acababa con cuatro botones de guardar.
 *
 * El esqueleto va **dentro** de `SpaceShell` y es el mismo que pinta el
 * `loading.tsx` de la ruta: con él fuera, la cabecera del espacio aparecía, se
 * iba mientras llegaba el perfil y volvía.
 */

import { AvisoCambiosSinGuardar } from "@/components/aviso-cambios-sin-guardar";
import { Aviso, EnlaceIr } from "@/components/console/panel";
import { SpaceShell } from "@/components/layout/space-shell";
import { useMetaFilters } from "@/hooks/use-meta-filters";
import { formatDateTime } from "@/lib/utils";
import { cuerpoDePerfil, usePerfilScoring } from "./_hooks/use-perfil-scoring";
import { useVistaPrevia } from "./_hooks/use-vista-previa";
import { AmbitoOrganizacion } from "./_components/ambito-organizacion";
import { AmbitoPerfilCard } from "./_components/ambito-perfil-card";
import { CpvsInteresCard, KeywordsAfinidadCard } from "./_components/afinidad-cards";
import { BarraGuardado } from "./_components/barra-guardado";
import { PerfilEsqueleto } from "./_components/perfil-esqueleto";
import { PesosPropuestosCard } from "./_components/pesos-propuestos-card";
import { PesosScoringCard } from "./_components/pesos-scoring-card";
import { RangoImporteCard } from "./_components/rango-importe-card";
import { VistaPreviaCard } from "./_components/vista-previa-card";

/** Título de una de las dos mitades del formulario. */
function TituloSeccion({ id, children, pista }: { id: string; children: React.ReactNode; pista: string }) {
  return (
    <div>
      <h2 id={id} className="font-display text-tf-lede font-semibold">
        {children}
      </h2>
      <p className="text-tf-meta text-muted-foreground">{pista}</p>
    </div>
  );
}

export default function MiPerfilPage() {
  const perfil = usePerfilScoring();
  const { data, saveMut, deleteMut } = perfil;
  const catalogoCpv = useMetaFilters().data?.cpv_nombres ?? [];
  const previa = useVistaPrevia(cuerpoDePerfil(perfil.valores, perfil.organizationId), {
    enabled: !perfil.isLoading && perfil.weightsValid,
  });

  if (perfil.isLoading) {
    return (
      <SpaceShell spaceKey="mi-perfil">
        <PerfilEsqueleto />
      </SpaceShell>
    );
  }

  const motivoBloqueo = perfil.weightsValid
    ? null
    : (perfil.weights.afinidad ?? 0) >= 100
      ? "La afinidad no puede quedarse con los 100 puntos: deja algo a otra dimensión."
      : "Los pesos deben sumar 100 para guardar.";

  return (
    <SpaceShell spaceKey="mi-perfil">
      <AvisoCambiosSinGuardar activo={perfil.dirty} />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,42rem)_minmax(0,1fr)] xl:items-start">
        <div className="space-y-6">
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

          {/* Arriba, antes del primer campo: una etiqueta de «heredado» al final
              de la página no contaba que todo lo de encima era de otra persona,
              ni que guardar crea un perfil nuevo en vez de editar el del equipo. */}
          {perfil.inherited && (
            <Aviso tone="info" role="note" title="Estás usando el perfil compartido de tu organización">
              Lo que ves aquí lo configuró otra persona. Al guardar creas tu propio perfil, privado salvo que lo
              compartas; el de la organización no cambia.
            </Aviso>
          )}

          <section aria-labelledby="mp-intereses" className="space-y-4">
            <TituloSeccion id="mp-intereses" pista="Lo que hace que una licitación sea de las tuyas.">
              Qué te interesa
            </TituloSeccion>
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
              catalogo={catalogoCpv}
            />
            <RangoImporteCard
              importeMin={perfil.importeMin}
              importeMax={perfil.importeMax}
              onImporteMinChange={perfil.setImporteMin}
              onImporteMaxChange={perfil.setImporteMax}
              errores={perfil.errores}
            />
          </section>

          <section aria-labelledby="mp-pesos" className="space-y-4">
            <TituloSeccion id="mp-pesos" pista="Cómo se reparten los 100 puntos del score entre las dimensiones.">
              Cuánto pesa cada criterio
            </TituloSeccion>
            <PesosScoringCard
              weights={perfil.weights}
              onWeightsChange={perfil.setWeights}
              onWeightChange={perfil.handleWeightChange}
              onReset={perfil.handleResetWeights}
            />
            {/* Pegada a los sliders que propone cambiar: leerla en otro sitio
                obligaría a recordar los seis números de arriba. */}
            <PesosPropuestosCard bloqueada={perfil.dirty} />
          </section>

          <section aria-labelledby="mp-ambito" className="space-y-4">
            <TituloSeccion id="mp-ambito" pista="Con quién compartes este perfil y qué decide tu organización.">
              Quién lo usa
            </TituloSeccion>
            <AmbitoPerfilCard
              shared={perfil.sharedWithOrganization}
              onSharedChange={perfil.setSharedWithOrganization}
            />
            <AmbitoOrganizacion />
            <p className="text-tf-meta text-muted-foreground">
              <EnlaceIr href="/ajustes?vista=cuenta">Exportar o eliminar tus datos, en Ajustes › Datos y cuenta</EnlaceIr>
            </p>
          </section>

          <BarraGuardado
            dirty={perfil.dirty}
            motivoBloqueo={motivoBloqueo}
            guardando={saveMut.isPending}
            onGuardar={perfil.guardar}
            onDescartar={perfil.descartar}
            puedeEliminar={perfil.hasProfile && !perfil.inherited}
            eliminando={deleteMut.isPending}
            onEliminar={() => deleteMut.mutate()}
          />
        </div>

        <aside aria-label="Vista previa del Radar" className="xl:sticky xl:top-0 xl:max-w-xl">
          <VistaPreviaCard
            previa={previa.data}
            cargando={previa.cargando}
            desfasada={previa.desfasada}
            error={previa.error}
            onRetry={() => void previa.refetch()}
            conCambios={perfil.dirty}
            disponible={perfil.weightsValid}
          />
        </aside>
      </div>
    </SpaceShell>
  );
}
