"use client";

/**
 * Identidad relacional de la empresa: miembros de la UTE, UTEs en las que
 * participa y los alias con los que aparece en fuente.
 *
 * Solo se pinta si hay algo que contar; los alias, además, solo cuando hay más
 * de uno (el único alias es el nombre canónico y no informa de nada).
 */

import { Handshake } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import type { EmpresaDetail } from "../_lib/types";

/** Alias visibles antes de resumir el resto en un contador. */
const MAX_ALIASES = 12;

export function EmpresaRelaciones({ detail }: { detail: EmpresaDetail }) {
  const hayAlgo =
    detail.ute_miembros.length > 0 ||
    detail.participa_en_utes.length > 0 ||
    detail.aliases.length > 1;
  if (!hayAlgo) return null;

  return (
    <>
      <Separator />
      <div className="grid gap-6 lg:grid-cols-2">
        {detail.ute_miembros.length > 0 && (
          <div>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <Handshake className="h-4 w-4" /> Miembros de la UTE
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {detail.ute_miembros.map((m) => (
                <Badge key={m.empresa_id} variant="secondary">
                  {m.nombre_canonico}
                </Badge>
              ))}
            </div>
          </div>
        )}
        {detail.participa_en_utes.length > 0 && (
          <div>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <Handshake className="h-4 w-4" /> Participa en UTEs
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {detail.participa_en_utes.map((u) => (
                <Badge key={u.empresa_id} variant="secondary">
                  {u.nombre_canonico}
                </Badge>
              ))}
            </div>
          </div>
        )}
        {detail.aliases.length > 1 && (
          <div>
            <h3 className="mb-2 text-sm font-semibold">
              Aliases vistos en fuente ({detail.aliases.length})
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {detail.aliases.slice(0, MAX_ALIASES).map((a, i) => (
                <Badge key={i} variant="outline" className="font-normal">
                  {a.alias_normalizado}
                </Badge>
              ))}
              {detail.aliases.length > MAX_ALIASES && (
                <span className="text-xs text-muted-foreground">
                  +{detail.aliases.length - MAX_ALIASES} más
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
