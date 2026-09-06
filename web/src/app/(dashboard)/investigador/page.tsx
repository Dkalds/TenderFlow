"use client";

/**
 * Investigador — búsqueda semántica sobre el corpus y conversación con el LLM.
 *
 * El estado y las dos llamadas viven en `_hooks/use-investigador.ts`; cada
 * bloque de pantalla, en `_components/`. Aquí queda el orden de la página y qué
 * se ve en cada estado.
 */

import { useInvestigador } from "./_hooks/use-investigador";
import { InvestigadorChatPanel } from "./_components/investigador-chat-panel";
import { InvestigadorConfigPanel } from "./_components/investigador-config-panel";
import { MensajeVacio, PreguntasEjemplo } from "./_components/investigador-empty";
import { InvestigadorError, InvestigadorSkeleton } from "./_components/investigador-feedback";
import { InvestigadorResults } from "./_components/investigador-results";
import { InvestigadorSearchBar } from "./_components/investigador-search-bar";
import { SpaceShell } from "@/components/layout/space-shell";

export default function InvestigadorPage() {
  const inv = useInvestigador();
  const { chat } = inv;
  const hayConversacion = chat.messages.length > 0 || chat.loading || Boolean(chat.error);

  const preguntar = (q: string) => {
    inv.setQuery(q);
    inv.submit(q);
  };

  return (
    <SpaceShell spaceKey="investigador">
      <div className="space-y-6">
        <InvestigadorConfigPanel
          config={inv.config}
          onChange={inv.updateConfig}
          models={inv.models}
        />

        <InvestigadorSearchBar
          mode={inv.mode}
          onModeChange={inv.setMode}
          query={inv.query}
          onQueryChange={inv.setQuery}
          onSubmit={inv.submit}
          busy={inv.loading || chat.loading}
          history={inv.history}
          activeSearchFilters={inv.activeSearchFilters}
        />

        {inv.showEmpty && <PreguntasEjemplo onPick={preguntar} />}

        {inv.loading && <InvestigadorSkeleton />}

        {inv.error && <InvestigadorError message={inv.error} />}

        {/* Resultados y conversación **conviven**: antes se excluían, así que
            preguntar por un resultado te hacía perder la lista desde la que
            preguntabas. En pantalla ancha van en paneles contiguos. */}
        <div className="grid items-start gap-4 xl:grid-cols-2">
          {!inv.loading && inv.searchResults && (
            <InvestigadorResults
              results={inv.searchResults}
              source={inv.searchSource}
              query={inv.query}
            />
          )}

          {hayConversacion && <InvestigadorChatPanel chat={chat} />}
        </div>

        {inv.showEmpty && <MensajeVacio />}
      </div>
    </SpaceShell>
  );
}
