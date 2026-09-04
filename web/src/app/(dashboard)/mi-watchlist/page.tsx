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
 * cambio de pestaña porque cambiar de pestaña no navega.
 */

import { SpaceShell } from "@/components/layout/space-shell";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
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
        {/* El nombre lo pone la cabecera del espacio; queda la nota que explica
            de dónde sale el conteo, que no es evidente y sí importa. */}
        <p className="max-w-[80ch] text-xs text-muted-foreground">
          Reglas de seguimiento guardadas en tu cuenta: el conteo de coincidencias
          es real (sobre todo el dataset) y las alertas por frecuencia se envían
          desde el servidor.
        </p>

        {/* Tabs: reglas de criterio vs. licitaciones individuales marcadas */}
        <div className="inline-flex rounded-lg border border-border/70 p-1" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={w.tab === t.key}
              onClick={() => w.setTab(t.key)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                w.tab === t.key
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

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
              onUpdate={w.updateRule}
              onEdit={w.setEditingRule}
              onDelete={w.deleteRule}
            />

            <EditRuleSheet
              key={w.editingRule?.id ?? "none"}
              rule={w.editingRule}
              ccaaList={w.ccaaList}
              onClose={() => w.setEditingRule(null)}
              onSave={w.saveEdit}
              saving={w.savingEdit}
            />

            {w.activeRules.length > 0 && (
              <ResultadosCombinados
                combined={w.combined}
                loading={w.matchesLoading}
              />
            )}
          </>
        )}
      </div>
    </SpaceShell>
  );
}
