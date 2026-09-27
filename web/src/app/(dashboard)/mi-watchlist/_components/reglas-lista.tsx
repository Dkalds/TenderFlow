"use client";

/**
 * Listado de reglas con sus cuatro estados: cargando, fallo, vacío y con datos.
 *
 * El estado vacío apunta al formulario de arriba en vez de repetir un botón:
 * el alta ya está en pantalla y un segundo CTA que hace scroll a otro sitio
 * fue justo lo que se retiró del resto de pantallas del dash.
 *
 * El fallo va antes que el vacío: sin él, una carga fallida se leía como «No
 * tienes reglas», que es justo lo que no se sabe.
 */

import { PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import type { ApiRule, RuleBody } from "../_hooks/watchlist-rule-types";
import { ReglaCard } from "./regla-card";

export function ReglasLista({
  rules,
  loading,
  error,
  onRetry,
  onUpdate,
  onEdit,
  onDelete,
}: {
  rules: ApiRule[] | undefined;
  loading: boolean;
  error?: unknown;
  onRetry?: () => void;
  onUpdate: (id: number, body: RuleBody) => void;
  onEdit: (rule: ApiRule) => void;
  onDelete: (id: number) => void;
}) {
  const ruleCount = rules?.length ?? 0;
  const hayError = error != null && !rules;

  return (
    <div>
      <PanelTitle as="h2" title={hayError ? "Reglas" : `Reglas (${ruleCount})`} />

      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2].map((i) => (
            <Skeleton key={i} className="h-36 w-full rounded-xl" />
          ))}
        </div>
      ) : hayError ? (
        <PanelError title="No se pudieron cargar tus reglas" error={error} onRetry={onRetry} />
      ) : ruleCount === 0 ? (
        <PanelEmpty
          title="No tienes reglas de seguimiento configuradas"
          hint="Crea una regla y recibirás un aviso, con la frecuencia que elijas, cuando entren licitaciones que la cumplan. Empieza con «Nueva regla de seguimiento», arriba."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {(rules ?? []).map((rule) => (
            <ReglaCard key={rule.id} rule={rule} onUpdate={onUpdate} onEdit={onEdit} onDelete={onDelete} />
          ))}
        </div>
      )}
    </div>
  );
}
