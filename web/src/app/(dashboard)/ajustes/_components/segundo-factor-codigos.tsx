"use client";

/**
 * Los códigos de recuperación, recién emitidos. **Solo se ven aquí**: la base
 * guarda su hash Argon2, así que no hay forma de volver a pedirlos. Por eso el
 * aviso no se va solo: desaparece cuando la persona dice que ya los guardó.
 */

import { Copy } from "lucide-react";
import { Aviso } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { copiarAlPortapapeles } from "@/lib/portapapeles";

export function SegundoFactorCodigos({ codigos, onGuardados }: { codigos: string[]; onGuardados: () => void }) {
  return (
    <Aviso tone="warning" role="alert" title="Guarda ahora tus códigos de recuperación">
      <p className="text-muted-foreground">
        La verificación en dos pasos ya está activa. Si pierdes el móvil, cada uno de estos códigos te deja entrar
        una vez. No se pueden volver a ver.
      </p>
      <ul aria-label="Códigos de recuperación" className="mt-2 grid grid-cols-2 gap-1 sm:grid-cols-5">
        {codigos.map((codigo) => (
          <li key={codigo} className="rounded-md bg-muted px-2 py-1 font-mono text-tf-meta">
            {codigo}
          </li>
        ))}
      </ul>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => void copiarAlPortapapeles(codigos.join("\n"), "Códigos copiados")}
        >
          <Copy aria-hidden="true" />
          Copiar los diez
        </Button>
        <Button size="sm" variant="ghost" onClick={onGuardados}>
          Ya los he guardado
        </Button>
      </div>
    </Aviso>
  );
}
