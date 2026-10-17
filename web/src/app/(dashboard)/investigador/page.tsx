"use client";

/**
 * Investigador — buscar en las licitaciones y en sus pliegos, y preguntar al
 * asistente.
 *
 * El estado y las llamadas viven en `_hooks/use-investigador.ts`; cada bloque
 * de pantalla, en `_components/`. Aquí queda el orden de la página y qué se ve
 * en cada estado: primero la caja de consulta, debajo las opciones avanzadas
 * (plegadas) y luego los ejemplos o, con una consulta hecha, la barra del
 * asistente y la lista de resultados.
 *
 * La conversación es la del asistente único de la consola, que se abre a la
 * derecha sin ser modal. Mientras está abierto, en pantalla ancha la página le
 * deja su hueco: resultados y asistente **conviven**, como desde que dejaron de
 * excluirse, y se marcan resultados con el asistente a la vista.
 */

import { useInvestigador } from "./_hooks/use-investigador";
import { InvestigadorAsistente } from "./_components/investigador-asistente";
import { InvestigadorConfigPanel } from "./_components/investigador-config-panel";
import { ConsultasDeEjemplo, MensajeVacio } from "./_components/investigador-empty";
import { InvestigadorError, InvestigadorSkeleton } from "./_components/investigador-feedback";
import { InvestigadorResults } from "./_components/investigador-results";
import { InvestigadorSearchBar } from "./_components/investigador-search-bar";
import { chipsDeInterpretacion, enlaceDeAlerta, textoBuscado } from "./_lib/interpretacion";
import { SpaceShell } from "@/components/layout/space-shell";
import { useAsistente } from "@/lib/asistente-store";
import { cn } from "@/lib/utils";

export default function InvestigadorPage() {
  const inv = useInvestigador();
  const entendido = chipsDeInterpretacion(inv.interpretacion);
  // El panel del asistente mide 32rem (`sm:max-w-lg`); con su margen, la lista
  // no queda debajo de él.
  const asistenteAbierto = useAsistente((s) => s.abierto);

  return (
    <SpaceShell spaceKey="investigador">
      <div className={cn("space-y-4", asistenteAbierto && "xl:pr-[34rem]")}>
        <InvestigadorSearchBar
          texto={inv.texto}
          onTextoChange={inv.setTexto}
          onSubmit={inv.submit}
          busy={inv.buscando}
          history={inv.history}
          activeSearchFilters={inv.activeSearchFilters}
          entendido={entendido}
          buscadoComo={textoBuscado(inv.interpretacion, inv.consulta)}
          talCual={inv.talCual}
          onTalCualChange={inv.setTalCual}
        />

        <InvestigadorConfigPanel
          config={inv.config}
          onChange={inv.updateConfig}
          models={inv.models}
          fusionDisponible={inv.fusionDisponible}
        />

        {inv.showEmpty ? (
          <>
            <ConsultasDeEjemplo onPick={inv.submit} />
            <MensajeVacio />
          </>
        ) : (
          <div className="min-w-0 space-y-3">
            <InvestigadorAsistente
              consulta={inv.consulta}
              seleccion={inv.seleccion}
              onPreguntar={inv.preguntar}
              onQuitar={inv.quitarSeleccion}
              onAbrir={inv.abrirAsistente}
            />
            {inv.loading && <InvestigadorSkeleton />}
            {inv.error != null && <InvestigadorError error={inv.error} onRetry={inv.reintentar} />}
            {!inv.loading && inv.error == null && inv.searchResults && (
              <InvestigadorResults
                results={inv.searchResults}
                source={inv.searchSource}
                enlaceAlerta={enlaceDeAlerta({
                  texto: inv.interpretacion?.texto ?? inv.consulta,
                  ccaa: inv.filtros.ccaa?.length ? inv.filtros.ccaa : (inv.interpretacion?.ccaa ?? []),
                  tecnologia: inv.filtros.tecnologia ?? [],
                  importeMin: inv.interpretacion?.importe_min,
                  organo: inv.interpretacion?.organo,
                  procedimiento: inv.interpretacion?.procedimiento,
                })}
                hayFiltrosEntendidos={entendido.length > 0}
                hayAmbito={inv.activeSearchFilters.length > 0}
                onBuscarTalCual={() => inv.setTalCual(true)}
                seleccion={inv.seleccion}
                seleccionLlena={inv.seleccionLlena}
                onAlternar={inv.alternarSeleccion}
                hayMas={inv.hayMas}
                onMostrarMas={inv.mostrarMas}
                cargandoMas={inv.cargandoMas}
              />
            )}
          </div>
        )}
      </div>
    </SpaceShell>
  );
}
