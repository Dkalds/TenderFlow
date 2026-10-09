"use client";

/**
 * Investigador — buscar en las licitaciones y en sus pliegos, y preguntar al
 * asistente.
 *
 * El estado y las llamadas viven en `_hooks/use-investigador.ts`; cada bloque
 * de pantalla, en `_components/`. Aquí queda el orden de la página y qué se ve
 * en cada estado: primero la caja de consulta, debajo las opciones avanzadas
 * (plegadas) y luego los ejemplos o, con una consulta hecha, la lista de
 * resultados y el asistente uno junto al otro.
 */

import { useInvestigador } from "./_hooks/use-investigador";
import { InvestigadorChatPanel } from "./_components/investigador-chat-panel";
import { InvestigadorConfigPanel } from "./_components/investigador-config-panel";
import { ConsultasDeEjemplo, MensajeVacio } from "./_components/investigador-empty";
import { InvestigadorError, InvestigadorSkeleton } from "./_components/investigador-feedback";
import { InvestigadorResults } from "./_components/investigador-results";
import { InvestigadorSearchBar } from "./_components/investigador-search-bar";
import { chipsDeInterpretacion, enlaceDeAlerta } from "./_lib/interpretacion";
import { SpaceShell } from "@/components/layout/space-shell";

export default function InvestigadorPage() {
  const inv = useInvestigador();
  const entendido = chipsDeInterpretacion(inv.interpretacion);

  return (
    <SpaceShell spaceKey="investigador">
      <div className="space-y-4">
        <InvestigadorSearchBar
          texto={inv.texto}
          onTextoChange={inv.setTexto}
          onSubmit={inv.submit}
          busy={inv.loading}
          history={inv.history}
          activeSearchFilters={inv.activeSearchFilters}
          entendido={entendido}
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
          /* Resultados y asistente **conviven**: antes se excluían, así que
             preguntar por un resultado hacía perder la lista desde la que se
             preguntaba. En pantalla ancha van en paneles contiguos, la lista
             algo más ancha: es lo que se recorre. */
          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <div className="min-w-0 space-y-3">
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
                  })}
                  hayFiltrosEntendidos={entendido.length > 0}
                  hayAmbito={inv.activeSearchFilters.length > 0}
                  onBuscarTalCual={() => inv.setTalCual(true)}
                  seleccion={inv.seleccion}
                  seleccionLlena={inv.seleccionLlena}
                  onAlternar={inv.alternarSeleccion}
                />
              )}
            </div>

            <InvestigadorChatPanel
              chat={inv.chat}
              onPreguntar={inv.preguntar}
              consulta={inv.consulta}
              seleccion={inv.seleccion}
              onQuitar={inv.quitarSeleccion}
            />
          </div>
        )}
      </div>
    </SpaceShell>
  );
}
