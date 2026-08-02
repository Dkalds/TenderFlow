"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { findPage } from "@/lib/navigation";
import { useWithFilters } from "@/lib/filters";

/**
 * Atajos al análisis en profundidad. Los gráficos detallados viven en sus
 * vistas; el Resumen sólo enlaza a ellas para no duplicarlos, y los atajos
 * arrastran el ámbito activo (`useWithFilters`) para no perder el contexto al
 * saltar. La metadata sale de `lib/navigation.ts`, única fuente de verdad.
 */
const SLUGS = ["tendencias", "organos", "tecnologias", "proyectos-modulos"] as const;

export function AtajosAnalisis() {
  const withFilters = useWithFilters();

  return (
    <section aria-labelledby="atajos-analisis-title">
      <div className="mb-2.5 flex items-baseline gap-2.5">
        <h2 id="atajos-analisis-title" className="text-xs font-semibold">
          Análisis completo
        </h2>
        <span className="text-[10.5px] text-muted-foreground">
          los gráficos detallados viven en sus vistas · los atajos arrastran el ámbito
        </span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {SLUGS.map((slug) => {
          const page = findPage(slug);
          if (!page) return null;
          const Icon = page.icon;
          return (
            <Link
              key={slug}
              href={withFilters(`/${slug}`)}
              aria-label={`Ir a ${page.label}`}
              className="group flex min-h-[104px] flex-col rounded-xl border border-border/60 bg-card/70 px-3.5 py-3 transition-[transform,border-color] duration-140 ease-out hover:-translate-y-px hover:border-primary/45"
            >
              <div className="mb-2.5 flex items-center gap-2.5">
                <span className="grid h-7 w-7 flex-none place-items-center rounded-lg bg-primary/12 text-primary">
                  <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                </span>
                <div className="flex-1" />
                <ArrowRight
                  className="h-3 w-3 flex-none text-muted-foreground transition-[color,transform] duration-140 ease-out group-hover:translate-x-0.5 group-hover:text-primary"
                  aria-hidden="true"
                />
              </div>
              <div className="mb-1 text-xs font-semibold leading-[1.3]">{page.label}</div>
              <div className="line-clamp-2 text-[10.5px] leading-[1.45] text-muted-foreground">
                {page.description}
              </div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
