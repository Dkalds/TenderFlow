"use client";

import * as React from "react";
import { PanelEmpty } from "@/components/console/panel";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ComparacionFichasTabla } from "@/components/pliego/comparar-fichas";
import { MAX_COMPARAR } from "@/hooks/use-comparar-fichas";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { cn, EMPTY, formatCurrency, formatDate } from "@/lib/utils";
import type { LicitacionDetail } from "@/lib/licitacion-detail";

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
  if (value == null) return EMPTY;
  if (key === "importe") return formatCurrency(value as number);
  if (key.startsWith("fecha")) return formatDate(value as string);
  return String(value);
}

export function Comparator({ items, onClose, className }: ComparatorProps) {
  // F2.8 — las fichas del pliego se comparan a petición: la tabla de arriba
  // es lo que ya se ve en el listado, y la de fichas es la que decide entre
  // dos pliegos (solvencia, criterios, garantías). Montada sólo al pedirla.
  const [conFichas, setConFichas] = React.useState(false);
  const puedeFichas = items.length >= 2 && items.length <= MAX_COMPARAR;
  return (
    // Centered modal, so DialogContent keeps the default transform-origin:
    // center rather than the trigger-anchored origin used by Sheet/DropdownMenu/
    // Popover (apple-design §7 / emil-design-eng: modals are exempt).
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={cn("mx-4 max-h-[90vh] w-full max-w-6xl overflow-auto", className)}>
        <DialogTitle>Comparar licitaciones</DialogTitle>
        <div>
          {items.length === 0 ? (
            <PanelEmpty size="sm" hint="No hay licitaciones para comparar." />
          ) : (
            <table className="text-tf-body w-full">
              <caption className="sr-only">Comparación de licitaciones</caption>
              <thead>
                <tr className="border-border border-b">
                  <th scope="col" className={cn(CABECERA_COLUMNA, "w-40 py-2 pr-4 text-left")}>
                    Campo
                  </th>
                  {items.map((item) => (
                    <th
                      key={item.id_externo}
                      scope="col"
                      className="text-tf-meta px-2 py-2 text-left font-mono font-medium"
                    >
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
                    <tr key={key} className="border-border border-b last:border-b-0">
                      <th scope="row" className="text-muted-foreground py-2 pr-4 text-left font-medium">
                        {label}
                      </th>
                      {values.map((val, i) => (
                        <td
                          key={i}
                          // Las celdas que difieren entre expedientes, con el tinte
                          // de aviso: es lo que hay que mirar.
                          className={cn("px-2 py-2", !allSame && "bg-warning/10", key === "cpv" && "font-mono")}
                        >
                          {key === "estado" ? (
                            <Badge size="sm" variant="outline">
                              {val}
                            </Badge>
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
          {puedeFichas && (
            <section className="border-border mt-6 border-t pt-4" aria-label="Fichas del pliego">
              {conFichas ? (
                // Cabeceras por id, como la tabla de arriba: las dos se leen
                // columna contra columna.
                <ComparacionFichasTabla ids={items.map((item) => item.id_externo)} />
              ) : (
                <Button variant="outline" size="sm" onClick={() => setConFichas(true)}>
                  Comparar también las fichas del pliego
                </Button>
              )}
            </section>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
