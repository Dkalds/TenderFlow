"use client";

/**
 * Aviso persistente con el secret recién creado.
 *
 * No desaparece solo a propósito: no hay endpoint que vuelva a exponer el
 * secret, así que un toast efímero para un valor irrecuperable sería una
 * trampa. Se cierra cuando el usuario dice que ya lo guardó.
 */

import { AlertTriangle, Copy } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

export function SecretNotice({ secret, onDismiss }: { secret: string; onDismiss: () => void }) {
  return (
    <div role="alert" className="border-warning/40 bg-warning/10 mb-4 rounded-lg border p-4 text-sm">
      <div className="flex items-start gap-2">
        <AlertTriangle className="text-warning mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="font-medium">Guardá este secret ahora</p>
          <p className="text-muted-foreground mt-1 text-xs">
            Es la única vez que se muestra: sirve para verificar la firma HMAC de cada entrega y no hay forma de
            recuperarlo después.
          </p>
          <code className="bg-background mt-2 block truncate rounded border px-2 py-1.5 font-mono text-xs">
            {secret}
          </code>
          <div className="mt-2 flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                void navigator.clipboard?.writeText(secret);
                toast.success("Secret copiado al portapapeles");
              }}
            >
              <Copy className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
              Copiar
            </Button>
            <Button size="sm" variant="ghost" onClick={onDismiss}>
              Ya lo guardé
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
