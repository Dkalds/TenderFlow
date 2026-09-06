"use client";

/**
 * Los dos bloques que solo se ven cuando la consola está en blanco: las
 * preguntas de ejemplo (arriba) y el cartel que explica los dos modos (abajo).
 */

import { Search, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { EXAMPLE_QUESTIONS } from "../_lib/config-storage";

export function PreguntasEjemplo({ onPick }: { onPick: (question: string) => void }) {
  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <Sparkles className="text-muted-foreground h-4 w-4" />
        <span className="text-muted-foreground text-sm font-medium">Preguntas de ejemplo</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {EXAMPLE_QUESTIONS.map((eq) => (
          <Badge
            key={eq}
            variant="outline"
            className="hover:bg-accent cursor-pointer px-3 py-1.5 text-sm"
            role="button"
            tabIndex={0}
            onClick={() => onPick(eq)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onPick(eq);
              }
            }}
          >
            {eq}
          </Badge>
        ))}
      </div>
    </div>
  );
}

export function MensajeVacio() {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center justify-center py-12 text-center">
        <Search className="text-muted-foreground/50 mb-4 h-12 w-12" />
        <p className="text-muted-foreground text-lg font-medium">
          Introduce una consulta para buscar en el corpus de licitaciones
        </p>
        <p className="text-muted-foreground/70 mt-1 text-sm">
          Usa el modo &quot;Búsqueda&quot; para resultados semánticos o &quot;Preguntar&quot; para conversar con el
          asistente (corpus + conocimiento general).
        </p>
      </CardContent>
    </Card>
  );
}
