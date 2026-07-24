"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { findPage } from "@/lib/navigation";
import { useWithFilters } from "@/lib/filters";

/**
 * Atajos al análisis en profundidad. Los charts detallados (evolución mensual,
 * tecnologías, tipos de proyecto, ranking de órganos) viven en sus páginas
 * dedicadas; el Resumen solo enlaza a ellas para no duplicar. Reutiliza la
 * metadata de navegación (label/descripción/icono) como única fuente de verdad.
 */
const SLUGS = ["tendencias", "organos", "tecnologias", "proyectos-modulos"] as const;

export function AtajosAnalisis() {
  const withFilters = useWithFilters();

  return (
    <section aria-labelledby="atajos-analisis-title" className="space-y-3">
      <h2 id="atajos-analisis-title" className="text-sm font-semibold text-muted-foreground">
        Análisis completo
      </h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {SLUGS.map((slug) => {
          const page = findPage(slug);
          if (!page) return null;
          const Icon = page.icon;
          return (
            <Link
              key={slug}
              href={withFilters(`/${slug}`)}
              aria-label={`Ir a ${page.label}`}
              className="block rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              <Card className="group h-full min-h-[7.75rem] transition-[transform,border-color,box-shadow] duration-200 hover:-translate-y-0.5 hover:border-primary/45 hover:shadow-lg">
                <CardContent className="flex h-full flex-col gap-2 p-4">
                  <div className="flex items-center justify-between">
                    <span className="grid h-8 w-8 place-items-center rounded-md bg-primary/10 text-primary transition-colors group-hover:bg-primary/15">
                      <Icon className="h-4 w-4" />
                    </span>
                    <ArrowRight className="h-4 w-4 text-muted-foreground/50 transition-colors group-hover:text-primary" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold">{page.label}</p>
                    <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                      {page.description}
                    </p>
                  </div>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
