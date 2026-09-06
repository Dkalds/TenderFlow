"use client";

/**
 * Las licitaciones mejor puntuadas del órgano abierto, como tarjetas.
 *
 * El color del distintivo sale de la **banda que calculó el backend**, no de
 * cortes propios: este ranking usa ya el mismo motor que el Radar
 * (Caliente/Atractiva/Tibia/Descarte), y los umbrales 80/60 eran los del
 * scoring A/B/C/D que se retiró.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatCurrency, formatDate } from "@/lib/utils";

import type { TopScoredItem } from "../_hooks/use-organos-view";

export function OrganoTopScored({ items }: { items: TopScoredItem[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Top {items.length} por Score</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {items.slice(0, 30).map((s, i) => (
            <div key={i} className="rounded-lg border p-3 space-y-1">
              <div className="flex items-start justify-between gap-2">
                {s.url ? (
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm font-medium leading-tight line-clamp-2 hover:underline text-primary"
                  >
                    {s.titulo ?? s.id_externo}
                  </a>
                ) : (
                  <p className="text-sm font-medium leading-tight line-clamp-2">
                    {s.titulo ?? s.id_externo}
                  </p>
                )}
                <Badge
                  variant={
                    s.banda === "Caliente"
                      ? "default"
                      : s.banda === "Atractiva"
                        ? "secondary"
                        : "outline"
                  }
                  className="shrink-0"
                >
                  {s.banda ? `${s.banda} · ${s.score}` : s.score}
                </Badge>
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                {s.importe != null && (
                  <span className="font-medium text-foreground">
                    {formatCurrency(s.importe)}
                  </span>
                )}
                {(s.estado_desc || s.estado) && <span>{s.estado_desc ?? s.estado}</span>}
                {s.tipo_proyecto && <span>{s.tipo_proyecto}</span>}
                {s.ccaa && <span>{s.ccaa}</span>}
                {s.empresa && <span>🏢 {s.empresa}</span>}
                {s.baja_pct != null && <span>📉 {s.baja_pct.toFixed(1)}% baja</span>}
                {s.fecha_adjudicacion && <span>📅 {formatDate(s.fecha_adjudicacion)}</span>}
                {s.modulos_str && <span className="text-primary">{s.modulos_str}</span>}
              </div>
              {(s.tipo_contrato_desc || s.cpv_desc) && (
                <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground/80">
                  {s.tipo_contrato_desc && <span>📑 {s.tipo_contrato_desc}</span>}
                  {s.cpv_desc && (
                    <span className="truncate max-w-full" title={s.cpv_desc}>
                      🏷️ {s.cpv_desc}
                    </span>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
