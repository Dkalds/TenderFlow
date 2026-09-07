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
 *
 * Eran cuatro tarjetas de 104 px con icono, título y descripción — el mismo
 * peso visual que las tarjetas de «Mercado abierto», que sí traen un dato que
 * caduca. Con eso el pie de la pantalla competía con su cabecera y cuatro
 * enlaces de navegación ocupaban una banda entera. Vuelven a ser lo que son:
 * enlaces. La descripción no se pierde, pasa al `title` — la misma información,
 * a un hover de distancia, en vez de ocupando dos líneas que nadie relee.
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
      <div className="flex flex-wrap gap-2">
        {SLUGS.map((slug) => {
          const page = findPage(slug);
          if (!page) return null;
          const Icon = page.icon;
          return (
            <Link
              key={slug}
              href={withFilters(`/${slug}`)}
              aria-label={`Ir a ${page.label}`}
              title={page.description}
              className="group border-border/60 hover:border-primary/45 hover:bg-card/70 inline-flex h-8 items-center gap-2 rounded-lg border px-3 text-[11.5px] font-medium transition-[border-color,background-color] duration-140 ease-out"
            >
              <Icon className="text-muted-foreground h-3.5 w-3.5 flex-none" aria-hidden="true" />
              {page.label}
              <ArrowRight
                className="text-muted-foreground group-hover:text-primary h-3 w-3 flex-none transition-[color,transform] duration-140 ease-out group-hover:translate-x-0.5"
                aria-hidden="true"
              />
            </Link>
          );
        })}
      </div>
    </section>
  );
}
