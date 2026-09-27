import type { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PanelEmpty } from "@/components/console/panel";

export interface EmptyStateProps {
  /** Icono pequeño y gris en línea con el título (nunca una baldosa). */
  icon?: LucideIcon;
  /** Qué falta, en una línea. Pásalo siempre: no hay título por defecto. */
  title?: string;
  /** Por qué o qué hacer, concreto para esta pantalla. Pásalo siempre. */
  hint?: string;
  actionLabel?: string;
  onAction?: () => void;
  className?: string;
}

/**
 * Vacío heredado: ahora es un envoltorio de `PanelEmpty`, así que se dibuja
 * igual que el resto de la consola (sin la baldosa de icono tintada de 56 px).
 *
 * Ya no hay valores por defecto: el «Sin datos» con el icono de bandeja salía
 * idéntico en decenas de paneles y no decía qué faltaba. Cada llamada pasa su
 * `title` y su `hint` («Ningún CPV con adjudicaciones en el ámbito actual.»,
 * «Amplía las fechas o quita filtros.»).
 *
 * @deprecated Usa `PanelEmpty` de `@/components/console/panel`.
 */
export function EmptyState({ icon, title, hint, actionLabel, onAction, className }: EmptyStateProps) {
  return (
    <PanelEmpty
      title={title}
      hint={hint}
      icon={icon}
      className={className}
      action={
        actionLabel && onAction ? (
          <Button variant="outline" size="sm" onClick={onAction}>
            {actionLabel}
          </Button>
        ) : undefined
      }
    />
  );
}
