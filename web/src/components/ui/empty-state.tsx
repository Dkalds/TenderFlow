import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { Inbox, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface EmptyStateProps {
  icon?: LucideIcon;
  title?: string;
  hint?: string;
  actionLabel?: string;
  onAction?: () => void;
  className?: string;
}

export function EmptyState({
  icon: Icon = Inbox,
  title = t("common.no_data"),
  hint = t("common.no_data_hint"),
  actionLabel,
  onAction,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        // Sustituye a un skeleton de carga (cambio de estado ocasional):
        // fade-in para evitar que el contenido aparezca de golpe.
        "flex flex-col items-center justify-center gap-3 py-12 text-center animate-in fade-in-0",
        className,
      )}
      role="status"
    >
      <span className="grid h-14 w-14 place-items-center rounded-2xl border border-primary/15 bg-primary/8 text-primary">
        <Icon className="h-6 w-6" aria-hidden="true" />
      </span>
      <p className="text-sm font-semibold text-foreground">{title}</p>
      {hint && (
        <p className="max-w-sm text-xs text-muted-foreground">{hint}</p>
      )}
      {actionLabel && onAction && (
        <Button variant="outline" size="sm" onClick={onAction} className="mt-1">
          {actionLabel}
        </Button>
      )}
    </div>
  );
}
