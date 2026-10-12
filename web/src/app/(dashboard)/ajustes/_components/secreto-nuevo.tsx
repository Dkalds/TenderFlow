"use client";

/**
 * Aviso persistente con una clave recién acuñada, al crearla o al rotarla.
 *
 * No se va solo: no hay endpoint que vuelva a exponer el token (la base guarda
 * su hash), y un toast efímero para un valor irrecuperable sería una trampa.
 * Mismo criterio que la pantalla de webhooks.
 */

import type * as React from "react";
import { Copy } from "lucide-react";
import { Aviso } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { copiarAlPortapapeles } from "@/lib/portapapeles";

export function SecretoNuevo({
  secreto,
  children,
  onCerrar,
}: {
  secreto: string;
  /** Lo que hay que saber además del token: hasta cuándo vale la anterior. */
  children?: React.ReactNode;
  onCerrar: () => void;
}) {
  return (
    <Aviso tone="warning" role="alert" title="Guarda esta clave ahora">
      <p className="text-muted-foreground">No se puede volver a ver. Si la pierdes, tendrás que crear otra.</p>
      {children && <p className="mt-1">{children}</p>}
      <code className="mt-2 block overflow-x-auto rounded-md bg-muted p-2 font-mono text-tf-meta">{secreto}</code>
      <div className="mt-2 flex gap-2">
        <Button size="sm" variant="outline" onClick={() => void copiarAlPortapapeles(secreto, "Clave copiada")}>
          <Copy aria-hidden="true" />
          Copiar
        </Button>
        <Button size="sm" variant="ghost" onClick={onCerrar}>
          Ya la he guardado
        </Button>
      </div>
    </Aviso>
  );
}
