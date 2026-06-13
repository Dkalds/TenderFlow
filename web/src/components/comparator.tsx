"use client";

import * as React from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn, formatCurrency, formatDate } from "@/lib/utils";
import { X } from "lucide-react";
import type { LicitacionDetail } from "@/components/detail-panel";

interface ComparatorProps {
  items: LicitacionDetail[];
  onClose: () => void;
  className?: string;
}

const COMPARE_FIELDS: { key: keyof LicitacionDetail; label: string }[] = [
  { key: "titulo", label: "Título" },
  { key: "organo_contratacion", label: "Órgano de contratación" },
  { key: "importe", label: "Importe" },
  { key: "estado", label: "Estado" },
  { key: "ccaa", label: "CCAA" },
  { key: "cpv", label: "CPV" },
  { key: "tecnologia", label: "Tecnología" },
  { key: "tipo_contrato", label: "Tipo de contrato" },
  { key: "fecha_publicacion", label: "Fecha publicación" },
  { key: "fecha_limite", label: "Fecha límite" },
];

function formatValue(key: string, value: unknown): string {
  if (value == null) return "-";
  if (key === "importe") return formatCurrency(value as number);
  if (key.startsWith("fecha")) return formatDate(value as string);
  return String(value);
}

export function Comparator({ items, onClose, className }: ComparatorProps) {
  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="comparator-title"
      tabIndex={-1}
      onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
      className={cn("fixed inset-0 z-50 flex items-center justify-center bg-black/60", className)}
    >
      <Card className="relative w-full max-w-6xl max-h-[90vh] overflow-auto mx-4">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle id="comparator-title">Comparar licitaciones</CardTitle>
          <button
            onClick={onClose}
            className="rounded-sm p-1 opacity-70 hover:opacity-100 transition-opacity"
          >
            <X className="h-5 w-5" />
            <span className="sr-only">Cerrar</span>
          </button>
        </CardHeader>
        <CardContent>
          {items.length === 0 ? (
            <p>No hay licitaciones para comparar.</p>
          ) : (
          <table className="w-full text-sm">
            <caption className="sr-only">Comparación de licitaciones</caption>
            <thead>
              <tr className="border-b border-border">
                <th className="py-2 pr-4 text-left font-medium text-muted-foreground w-40">Campo</th>
                {items.map((item) => (
                  <th key={item.id_externo} className="py-2 px-2 text-left font-medium">
                    {item.id_externo}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {COMPARE_FIELDS.map(({ key, label }) => {
                const values = items.map((item) => formatValue(key, item[key]));
                const allSame = values.every((v) => v === values[0]);

                return (
                  <tr key={key} className="border-b border-border last:border-b-0">
                    <td className="py-2 pr-4 text-muted-foreground font-medium">{label}</td>
                    {values.map((val, i) => (
                      <td
                        key={i}
                        className={cn("py-2 px-2", !allSame && "bg-yellow-500/10")}
                      >
                        {key === "estado" ? (
                          <Badge variant="outline">{val}</Badge>
                        ) : (
                          val
                        )}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
