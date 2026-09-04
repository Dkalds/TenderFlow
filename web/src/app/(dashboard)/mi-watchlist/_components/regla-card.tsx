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

import { Eye, Mail, Pencil, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn, formatCurrency } from "@/lib/utils";
import {
  FREQ_LABEL,
  formatMatchCount,
  ruleToBody,
  type ApiRule,
  type RuleBody,
} from "../_hooks/use-watchlist-rules";

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
    <Card className={cn(!rule.active && "opacity-50")}>
      <CardHeader className="flex flex-row items-start justify-between pb-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <CardTitle className="text-base truncate">
              {rule.nombre || rule.keyword || "Regla"}
            </CardTitle>
            {/* El conteo del listado viene acotado por el backend
                (subselect con LIMIT, para no barrer 1,6M filas por
                regla): al tope se pinta «999+», no un falso exacto. */}
            <Badge
              variant="default"
              className="shrink-0"
              title={`${formatMatchCount(rule.match_count)} coincidencias`}
            >
              {formatMatchCount(rule.match_count)}
            </Badge>
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9"
                aria-label={rule.active ? "Desactivar regla" : "Activar regla"}
                aria-pressed={rule.active}
                onClick={() =>
                  onUpdate(rule.id, ruleToBody(rule, { active: !rule.active }))
                }
              >
                <Eye
                  aria-hidden="true"
                  className={cn(
                    "h-4 w-4",
                    rule.active ? "text-primary" : "text-muted-foreground",
                  )}
                />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{rule.active ? "Desactivar" : "Activar"}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9"
                aria-label="Editar regla"
                onClick={() => onEdit(rule)}
              >
                <Pencil className="h-4 w-4" aria-hidden="true" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Editar regla</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9 text-destructive"
                aria-label="Eliminar regla"
                onClick={() => onDelete(rule.id)}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Eliminar</TooltipContent>
          </Tooltip>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {rule.keyword && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Keyword:</span>
            <Badge variant="outline">{rule.keyword}</Badge>
          </div>
        )}
        {rule.cpv && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">CPV:</span>
            <Badge variant="outline">{rule.cpv}</Badge>
          </div>
        )}
        {rule.min_importe != null && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Min:</span>
            <Badge variant="secondary">{formatCurrency(rule.min_importe)}</Badge>
          </div>
        )}
        {rule.ccaa && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">CCAA:</span>
            <Badge variant="outline">{rule.ccaa}</Badge>
          </div>
        )}
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Frecuencia:</span>
          <span className="text-sm">{FREQ_LABEL[rule.frequency]}</span>
        </div>
        <div className="flex items-center gap-2">
          <Mail className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <span className="text-xs text-muted-foreground truncate">
            {rule.email ? rule.email : "Solo notificaciones in-app"}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
