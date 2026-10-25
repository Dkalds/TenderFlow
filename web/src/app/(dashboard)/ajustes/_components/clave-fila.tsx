"use client";

/**
 * Una clave del listado: su estado, cuándo se usó y, si sigue viva, rotarla o
 * revocarla.
 *
 * El estado sale de lo que la API manda: revocada si `is_active` es falso,
 * caducada si su `expires_at` ya pasó (la API la rechaza aunque siga activa,
 * y tampoco deja rotarla), viva en otro caso. El último uso es lo que decide
 * cuál retirar: una clave que nadie usa desde hace meses es la primera
 * candidata.
 */

import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { MiClave } from "@/hooks/use-ajustes";
import { formatDateTime } from "@/lib/utils";
import { RevocarClaveDialog, RotarClaveDialog } from "./clave-dialogos";

type EstadoClave = "viva" | "caducada" | "revocada";

function fecha(valor: string | null | undefined): Date | null {
  if (!valor) return null;
  const d = new Date(valor);
  return Number.isNaN(d.getTime()) ? null : d;
}

function estadoDe(clave: MiClave, ahora: Date): EstadoClave {
  if (!clave.is_active) return "revocada";
  const caduca = fecha(clave.expires_at);
  return caduca && caduca <= ahora ? "caducada" : "viva";
}

function detalle(clave: MiClave, estado: EstadoClave): string {
  const partes: string[] = [];
  const creada = fecha(clave.created_at);
  if (creada) partes.push(`Creada ${formatDateTime(creada)}`);
  const usada = fecha(clave.last_used);
  partes.push(usada ? `Último uso ${formatDateTime(usada)}` : "Sin usar todavía");
  const caduca = fecha(clave.expires_at);
  if (caduca && estado !== "revocada") {
    partes.push(`${estado === "caducada" ? "Caducó" : "Caduca"} ${formatDateTime(caduca)}`);
  }
  return partes.join(" · ");
}

export function ClaveFila({
  clave,
  onRotada,
}: {
  clave: MiClave;
  onRotada: (token: string, nota: string) => void;
}) {
  const [dialogo, setDialogo] = React.useState<"rotar" | "revocar" | null>(null);
  const estado = estadoDe(clave, new Date());
  const cerrar = (abierto: boolean) => {
    if (!abierto) setDialogo(null);
  };

  return (
    <li className="flex flex-wrap items-start justify-between gap-3 rounded-md border border-divider p-3">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 text-tf-body font-medium">
          {clave.name || `Clave ${clave.id}`}
          <Badge variant="secondary" size="sm">
            {clave.tier}
          </Badge>
          {estado !== "viva" && (
            <Badge variant="outline" size="sm">
              {estado === "revocada" ? "Revocada" : "Caducada"}
            </Badge>
          )}
        </p>
        <p className="mt-1 text-tf-meta text-muted-foreground">{detalle(clave, estado)}</p>
      </div>
      {estado === "viva" && (
        <div className="flex shrink-0 gap-2">
          <Button size="sm" variant="outline" onClick={() => setDialogo("rotar")}>
            Rotar
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setDialogo("revocar")}>
            Revocar
          </Button>
          <RotarClaveDialog clave={clave} open={dialogo === "rotar"} onOpenChange={cerrar} onRotada={onRotada} />
          <RevocarClaveDialog clave={clave} open={dialogo === "revocar"} onOpenChange={cerrar} />
        </div>
      )}
    </li>
  );
}
