"use client";

/**
 * Tarjeta de una regla: criterios, conteo de coincidencias y las tres acciones.
 *
 * Las tres acciones son icon-only y llevan `aria-label` + `Tooltip`: sin
 * etiqueta accesible un lector de pantalla anuncia «botón» tres veces seguidas
 * y no hay forma de saber cuál elimina. La regla `jsx-a11y/
 * control-has-associated-label` de `eslint.config.mjs` lo bloquea en CI
 * precisamente por esto.
 */

import type * as React from "react";
import { Eye, Mail, Pencil, Trash2 } from "lucide-react";
import { Panel } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn, formatCurrency } from "@/lib/utils";
import { ruleToBody } from "../_hooks/use-watchlist-rules";
import { formatMatchCount } from "../_hooks/watchlist-matches";
import { FREQ_LABEL } from "../_hooks/watchlist-rule-options";
import type { ApiRule, RuleBody } from "../_hooks/watchlist-rule-types";

/** Un criterio de la regla: rótulo y valor, en la misma línea. */
function Criterio({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <dt className="flex-none text-muted-foreground">{label}</dt>
      <dd className="min-w-0 truncate">{children}</dd>
    </div>
  );
}

export function ReglaCard({
  rule,
  onUpdate,
  onEdit,
  onDelete,
}: {
  rule: ApiRule;
  onUpdate: (id: number, body: RuleBody) => void;
  onEdit: (rule: ApiRule) => void;
  onDelete: (id: number) => void;
}) {
  return (
    <Panel className={cn(!rule.active && "opacity-50")}>
      <div className="mb-2.5 flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-tf-body font-semibold">{rule.nombre || rule.keyword || "Regla"}</h3>
          {/* El conteo del listado viene acotado por la API (para no barrer
              1,6M filas por regla): al tope se pinta «999+», no un falso
              exacto. */}
          <p className="tf-tnum text-tf-meta text-muted-foreground">
            {formatMatchCount(rule.match_count)} coincidencias
          </p>
        </div>
        <div className="flex flex-none items-center gap-0.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={rule.active ? "Desactivar regla" : "Activar regla"}
                aria-pressed={rule.active}
                onClick={() => onUpdate(rule.id, ruleToBody(rule, { active: !rule.active }))}
              >
                <Eye aria-hidden="true" className={rule.active ? "text-primary" : "text-muted-foreground"} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{rule.active ? "Desactivar" : "Activar"}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label="Editar regla" onClick={() => onEdit(rule)}>
                <Pencil aria-hidden="true" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Editar regla</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                className="text-destructive"
                aria-label="Eliminar regla"
                onClick={() => onDelete(rule.id)}
              >
                <Trash2 aria-hidden="true" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Eliminar</TooltipContent>
          </Tooltip>
        </div>
      </div>
      <dl className="space-y-1.5 text-tf-meta">
        {rule.keyword && (
          <Criterio label="Palabra clave">
            <Badge size="sm" variant="outline">
              {rule.keyword}
            </Badge>
          </Criterio>
        )}
        {rule.cpv && (
          <Criterio label="CPV">
            <span className="font-mono">{rule.cpv}</span>
          </Criterio>
        )}
        {rule.min_importe != null && (
          <Criterio label="Importe mínimo">
            <span className="tf-tnum">{formatCurrency(rule.min_importe)}</span>
          </Criterio>
        )}
        {rule.ccaa && <Criterio label="CCAA">{rule.ccaa}</Criterio>}
        <Criterio label="Frecuencia">{FREQ_LABEL[rule.frequency]}</Criterio>
      </dl>
      <p className="mt-2 flex items-center gap-1.5 text-tf-meta text-muted-foreground">
        <Mail className="h-3 w-3 flex-none" aria-hidden="true" />
        <span className="truncate">{rule.email ? rule.email : "Solo notificaciones en TenderFlow"}</span>
      </p>
    </Panel>
  );
}
