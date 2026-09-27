"use client";

/**
 * Mi Watchlist — reglas de criterio y licitaciones marcadas a mano.
 *
 * La página era un componente cliente de ~970 líneas con las queries, las
 * mutaciones, la migración del `localStorage` y el marcado en el mismo cuerpo.
 * Ahora solo compone: el comportamiento vive en `_hooks/use-mi-watchlist.ts` y
 * cada bloque de pantalla en `_components/`, que es el reparto que ya siguen
 * `mercado`, `ops` y `mi-pipeline`.
 *
 * Las dos pestañas no son rutas: el ámbito y las queries en caché sobreviven al
 * cambio de pestaña porque cambiar de pestaña no navega. Son `PanelTabs`, con
 * el teclado del patrón de pestañas y el cuerpo como su `tabpanel`.
 */

import { PanelTabs, panelDePestana } from "@/components/console/panel";
import { SpaceShell } from "@/components/layout/space-shell";
import { Separator } from "@/components/ui/separator";
import { EditRuleSheet } from "./_components/edit-rule-sheet";
import { FavoritosPanel } from "./_components/favoritos-panel";
import { NuevaReglaCard } from "./_components/nueva-regla-card";
import { ReglasLista } from "./_components/reglas-lista";
import { ResultadosCombinados } from "./_components/resultados-combinados";
import { useMiWatchlist, type WatchlistTab } from "./_hooks/use-mi-watchlist";

const TABS: { key: WatchlistTab; label: string }[] = [
  { key: "reglas", label: "Reglas" },
  { key: "favoritos", label: "Favoritos" },
];

export default function MiWatchlistPage() {
  const w = useMiWatchlist();

  return (
    <SpaceShell spaceKey="mi-watchlist">
      <div className="space-y-6">
        {/* Reglas de criterio frente a licitaciones marcadas una a una. */}
        <PanelTabs tabs={TABS} value={w.tab} onChange={w.setTab} label="Reglas o favoritos" idBase="watchlist" />

        <div {...panelDePestana("watchlist", w.tab)} className="space-y-6 rounded-md">
          {w.tab === "favoritos" ? (
            <FavoritosPanel />
          ) : (
            <>
              <NuevaReglaCard
                form={w.nueva}
                ccaaList={w.ccaaList}
                open={w.formOpen}
                onToggle={() => w.setFormOpen((o) => !o)}
              />

              <Separator />

              <ReglasLista
                rules={w.rules}
                loading={w.rulesLoading}
                error={w.rulesError}
                onRetry={w.refetchRules}
                onUpdate={w.updateRule}
                onEdit={w.setEditingRule}
                onDelete={w.deleteRule}
              />

              <EditRuleSheet
                key={w.editingRule?.id ?? "none"}
                rule={w.editingRule}
                ccaaList={w.ccaaList}
                tecnologiaList={w.tecnologiaList}
                onClose={() => w.setEditingRule(null)}
                onSave={w.saveEdit}
                saving={w.savingEdit}
              />

              {w.activeRules.length > 0 && <ResultadosCombinados combined={w.combined} loading={w.matchesLoading} />}
            </>
          )}
        </div>
      </div>
    </SpaceShell>
  );
}
