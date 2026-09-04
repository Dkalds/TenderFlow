"use client";

/**
 * Listado de reglas con sus tres estados: cargando, vacío y con datos.
 *
 * El estado vacío apunta al formulario de arriba en vez de repetir un botón:
 * el alta ya está en pantalla y un segundo CTA que hace scroll a otro sitio
 * fue justo lo que se retiró del resto de pantallas del dash.
 */

import { Eye } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { ApiRule, RuleBody } from "../_hooks/use-watchlist-rules";
import { ReglaCard } from "./regla-card";

export function ReglasLista({
  rules,
  loading,
  onUpdate,
  onEdit,
  onDelete,
}: {
  rules: ApiRule[] | undefined;
  loading: boolean;
  onUpdate: (id: number, body: RuleBody) => void;
  onEdit: (rule: ApiRule) => void;
  onDelete: (id: number) => void;
}) {
  const ruleCount = rules?.length ?? 0;

  return (
    <div>
      <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
        <Eye className="h-5 w-5" />
        Reglas ({ruleCount})
      </h2>

      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2].map((i) => (
            <Card key={i}>
              <CardContent className="pt-6">
                <Skeleton className="h-6 w-32 mb-2" />
                <Skeleton className="h-4 w-48" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : ruleCount === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <Eye className="h-12 w-12 text-muted-foreground/50 mb-4" />
            <p className="text-lg font-medium text-muted-foreground">
              No tienes reglas de seguimiento configuradas
            </p>
            <p className="text-sm text-muted-foreground/70 mt-1">
              Usa el formulario de arriba para crear tu primera regla.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {(rules ?? []).map((rule) => (
            <ReglaCard
              key={rule.id}
              rule={rule}
              onUpdate={onUpdate}
              onEdit={onEdit}
              onDelete={onDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
}
