"use client";

/**
 * Aviso persistente con el secreto recién creado.
 *
 * No desaparece solo a propósito: no hay endpoint que vuelva a exponer el
 * secreto, así que un toast efímero para un valor irrecuperable sería una
 * trampa. Se cierra cuando el usuario dice que ya lo guardó.
 */

import { Copy } from "lucide-react";
import { toast } from "sonner";
import { Aviso } from "@/components/console/panel";
import { Button } from "@/components/ui/button";

export function SecretNotice({ secret, onDismiss }: { secret: string; onDismiss: () => void }) {
  return (
    <Aviso tone="warning" role="alert" title="Guarda este secreto ahora">
      <p className="text-muted-foreground">
        Es la única vez que se muestra: sirve para verificar la firma HMAC de cada entrega y no hay forma de
        recuperarlo después.
      </p>
      <code className="bg-background mt-2 block truncate rounded-sm border border-border/60 px-2 py-1.5 font-mono text-tf-meta">
        {secret}
      </code>
      <div className="mt-2 flex gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            void navigator.clipboard?.writeText(secret);
            toast.success("Secreto copiado al portapapeles");
          }}
        >
          <Copy aria-hidden="true" />
          Copiar
        </Button>
        <Button size="sm" variant="ghost" onClick={onDismiss}>
          Ya lo he guardado
        </Button>
      </div>
    </Aviso>
  );
}
