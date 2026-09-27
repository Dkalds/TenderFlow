"use client";

/**
 * Aviso de secreto de un solo uso: ni el token de API ni el secreto de un
 * webhook se pueden volver a pedir, así que esta es la única ventana para
 * copiarlos. El mismo bloque servía a los dos, con dos copias del mismo botón.
 */

import { Copy } from "lucide-react";
import { toast } from "sonner";
import { Aviso } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).catch(() => {
    toast.error("No se pudo copiar. Copia manualmente: " + text);
  });
}

export function SecretRevealCard({
  aviso,
  secret,
  onClose,
  className,
}: {
  aviso: string;
  secret: string;
  onClose: () => void;
  className?: string;
}) {
  return (
    <Aviso tone="success" role="alert" title={aviso} className={className}>
      <div className="mt-1.5 flex items-center gap-2">
        <code className="bg-muted min-w-0 flex-1 break-all rounded-sm p-2 font-mono text-tf-meta">{secret}</code>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="outline" size="icon-sm" aria-label="Copiar" onClick={() => copyToClipboard(secret)}>
              <Copy aria-hidden="true" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Copiar</TooltipContent>
        </Tooltip>
      </div>
      <Button variant="ghost" size="sm" className="mt-2" onClick={onClose}>
        Cerrar
      </Button>
    </Aviso>
  );
}
