"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { PanelTitle } from "@/components/console/panel";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { findPage } from "@/lib/navigation";
import { useWithFilters } from "@/lib/filters";

/**
 * Atajos al análisis en profundidad. Los gráficos detallados viven en sus
 * vistas; el Resumen sólo enlaza a ellas para no duplicarlos, y los atajos
 * arrastran el ámbito activo (`useWithFilters`) para no perder el contexto al
 * saltar. La metadata sale de `lib/navigation.ts`, única fuente de verdad.
 *
 * Eran cuatro tarjetas de 104 px con icono, título y descripción — el mismo
 * peso visual que las tarjetas de «Mercado abierto», que sí traen un dato que
 * caduca. Vuelven a ser lo que son: enlaces, sin icono de página delante (el
 * enlace ya dice su destino, y tres de los cuatro pintaban el mismo glifo del
 * espacio que los absorbe). La descripción pasa a un tooltip, que a diferencia
 * del `title` nativo también se abre con el teclado. El hover solo cambia el
 * color: se ven a diario y nada se desplaza.
 */
const SLUGS = ["tendencias", "organos", "tecnologias", "proyectos-modulos"] as const;

export function AtajosAnalisis() {
  const withFilters = useWithFilters();

  return (
    <section aria-labelledby="atajos-analisis-title">
      <PanelTitle
        as="h2"
        id="atajos-analisis-title"
        title="Análisis completo"
        hint="con tu ámbito aplicado"
        className="mb-2.5"
      />
      <div className="flex flex-wrap gap-2">
        {SLUGS.map((slug) => {
          const page = findPage(slug);
          if (!page) return null;
          return (
            <Tooltip key={slug}>
              <TooltipTrigger asChild>
                <Link
                  href={withFilters(`/${slug}`)}
                  aria-label={`Ir a ${page.label}`}
                  className="group inline-flex h-8 items-center gap-2 rounded-md border border-border/60 bg-card px-3 text-tf-meta font-medium transition-colors hover:border-primary/50 active:bg-primary/10 active:duration-0"
                >
                  {page.label}
                  <ArrowRight
                    className="h-3 w-3 flex-none text-muted-foreground transition-colors group-hover:text-primary"
                    aria-hidden="true"
                  />
                </Link>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs">{page.description}</TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </section>
  );
}
