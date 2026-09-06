"use client";

/**
 * Tarjeta de secreto de un solo uso: ni el token de API ni el secret de un
 * webhook se pueden volver a pedir, así que esta es la única ventana para
 * copiarlos. El mismo bloque servía a los dos, con dos copias del mismo botón.
 */

import { Copy } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

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
    <Card className={cn("border-green-500 bg-green-50/50 dark:bg-green-950/20", className)}>
      <CardContent className="pt-4">
        <p className="mb-2 text-sm font-medium">{aviso}</p>
        <div className="flex items-center gap-2">
          <code className="bg-muted flex-1 rounded p-2 font-mono text-xs break-all">{secret}</code>
          <Button variant="outline" size="sm" onClick={() => copyToClipboard(secret)}>
            <Copy className="h-4 w-4" />
          </Button>
        </div>
        <Button variant="ghost" size="sm" className="mt-2" onClick={onClose}>
          Cerrar
        </Button>
      </CardContent>
    </Card>
  );
}
