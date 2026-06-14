import * as React from "react";
import { cn } from "@/lib/utils";

export interface PageHeaderProps {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  /** Optional eyebrow (small uppercase label above the title) */
  eyebrow?: React.ReactNode;
  className?: string;
}

/**
 * Consistent page header — title + description + actions, with uniform spacing.
 * Apply at the top of every dashboard page so the shell rhythm stays stable.
 */
export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
  className,
}: PageHeaderProps) {
  return (
    <header
      className={cn(
        "flex flex-col gap-3 pb-5 sm:flex-row sm:items-end sm:justify-between",
        className,
      )}
    >
      <div className="min-w-0 space-y-1">
        {eyebrow && (
          <p className="text-[11px] font-semibold uppercase tracking-wider text-primary/80">
            {eyebrow}
          </p>
        )}
        <h1 className="text-xl font-semibold leading-tight tracking-tight text-foreground sm:text-2xl">
          {title}
        </h1>
        {description && (
          <p className="max-w-2xl text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && (
        <div className="flex shrink-0 items-center gap-2 sm:justify-end">
          {actions}
        </div>
      )}
    </header>
  );
}
