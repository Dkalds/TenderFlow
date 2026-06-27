"use client";

import Link from "next/link";
import { Bell, CalendarClock, CalendarDays, ArrowRight } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type PipelinePageKey = "pipeline-alertas" | "renovaciones" | "calendario";

interface PageMeta {
  href: string;
  label: string;
  role: string;
  icon: LucideIcon;
}

const PAGES: Record<PipelinePageKey, PageMeta> = {
  "pipeline-alertas": {
    href: "/pipeline-alertas",
    label: "Pipeline & Alertas",
    role: "Oportunidades activas que están cerrando + forecast de re-licitación",
    icon: Bell,
  },
  renovaciones: {
    href: "/renovaciones",
    label: "Renovaciones",
    role: "Contratos ya adjudicados que vencen (riesgo de cambio de proveedor)",
    icon: CalendarClock,
  },
  calendario: {
    href: "/calendario",
    label: "Calendario",
    role: "Vista temporal de publicaciones y plazos por fecha",
    icon: CalendarDays,
  },
};

const ORDER: PipelinePageKey[] = ["pipeline-alertas", "renovaciones", "calendario"];

/**
 * Banda de orientación compartida por las tres páginas del territorio "qué viene":
 * declara el rol de la página actual y enlaza a las otras dos, para que el usuario
 * sepa cuál resuelve su "¿qué hago hoy?".
 *
 * RFC ux-pipeline-alertas — criterio "clarificar IA": pipeline-alertas / renovaciones
 * / calendario comparten territorio y se confundían; aquí cada una declara su rol.
 */
export function PipelineRoleNav({ current }: { current: PipelinePageKey }) {
  const me = PAGES[current];
  const others = ORDER.filter((key) => key !== current);
  const MeIcon = me.icon;

  return (
    <div
      className="rounded-lg border bg-muted/30 px-4 py-3"
      data-testid="pipeline-role-nav"
    >
      <p className="flex items-start gap-2 text-sm text-muted-foreground">
        <MeIcon
          className="mt-0.5 h-4 w-4 shrink-0 text-foreground"
          aria-hidden="true"
        />
        <span>
          <span className="font-medium text-foreground">{me.label}:</span>{" "}
          {me.role}.
        </span>
      </p>
      <nav
        className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1"
        aria-label="Páginas relacionadas"
      >
        <span className="text-xs text-muted-foreground">¿Buscás otra cosa?</span>
        {others.map((key) => {
          const other = PAGES[key];
          const Icon = other.icon;
          return (
            <Link
              key={key}
              href={other.href}
              className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              <Icon className="h-3.5 w-3.5" aria-hidden="true" />
              {other.label}
              <ArrowRight className="h-3 w-3" aria-hidden="true" />
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
