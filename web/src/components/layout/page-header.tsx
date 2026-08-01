import * as React from "react";
import { cn } from "@/lib/utils";

import type { LucideIcon } from "lucide-react";

export interface PageHeaderProps {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  /** Optional eyebrow (small uppercase label above the title) */
  eyebrow?: React.ReactNode;
  /** Icono del eyebrow. Solo se pinta en la variante `hero`. */
  eyebrowIcon?: LucideIcon;
  /**
   * `plain` (por defecto) para las páginas analíticas; `hero` para la entrada a
   * un espacio de producto — píldora, título display y halo.
   *
   * Existía un solo tratamiento y ninguna página lo usaba, así que cada una
   * maquetaba su cabecera a mano: Radar, Oportunidades y login acabaron con
   * `tf-display` y secciones hero, y el resto con `tf-h1` plano. Dos lenguajes
   * visuales por omisión, no por decisión.
   */
  variant?: "plain" | "hero";
  className?: string;
}

/**
 * Cabecera de página — título + descripción + acciones, con espaciado uniforme.
 * Va al principio de cada página del dashboard para que el ritmo del shell no
 * dependa de que cada una lo reinvente.
 */
export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
  eyebrowIcon: EyebrowIcon,
  variant = "plain",
  className,
}: PageHeaderProps) {
  const hero = variant === "hero";

  const content = (
    <div
      className={cn(
        "flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between",
        hero ? "relative" : "pb-5",
      )}
    >
      <div className="min-w-0 space-y-1">
        {eyebrow &&
          (hero ? (
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">
              {EyebrowIcon && <EyebrowIcon className="h-3.5 w-3.5" aria-hidden="true" />}
              {eyebrow}
            </div>
          ) : (
            <p className="text-[11px] font-semibold uppercase tracking-wider text-primary/80">
              {eyebrow}
            </p>
          ))}
        <h1 className={cn(hero ? "tf-display" : "tf-h1 text-foreground")}>{title}</h1>
        {description && (
          <p className={cn("max-w-2xl text-muted-foreground", hero ? "mt-2" : "text-sm")}>
            {description}
          </p>
        )}
      </div>
      {actions && (
        <div className={cn("flex shrink-0 items-center gap-2 sm:justify-end", hero && "relative")}>
          {actions}
        </div>
      )}
    </div>
  );

  if (!hero) return <header className={className}>{content}</header>;

  return (
    <header
      className={cn(
        "tf-card-shadow relative overflow-hidden rounded-xl border border-border bg-card/75 p-5 sm:p-7",
        className,
      )}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-24 -top-24 h-64 w-64 rounded-full bg-primary/10 blur-3xl"
      />
      {content}
    </header>
  );
}
