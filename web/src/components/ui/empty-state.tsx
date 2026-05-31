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
        "flex flex-col items-center justify-center gap-3 py-12 text-center",
        className,
      )}
      role="status"
    >
      <Icon className="h-10 w-10 text-muted-foreground/50" aria-hidden="true" />
      <p className="text-sm font-medium text-muted-foreground">{title}</p>
      {hint && (
        <p className="text-xs text-muted-foreground/70">{hint}</p>
      )}
      {actionLabel && onAction && (
        <Button variant="outline" size="sm" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  );
}
