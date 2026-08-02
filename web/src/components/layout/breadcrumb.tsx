"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { findPage, findProductSpace, findSection } from "@/lib/navigation";
import { useWithFilters } from "@/lib/filters";

/**
 * Migas de pan sobre el árbol real de navegación: `Espacio › Sección › Página`.
 *
 * Antes renderizaba `Espacio › Página`, saltándose el nivel Sección — que es
 * justamente el nivel al que enlaza la sidebar — y daba por hecho que toda ruta
 * no-Radar/Oportunidades colgaba de Mercado, así que anunciaba "Mercado ›
 * Administración" y "Mercado › Calidad de Datos". El espacio ahora se declara
 * en `NavSection.space` y se omite en las secciones que no cuelgan de ninguno.
 */
export function Breadcrumb() {
  const pathname = usePathname();
  const withFilters = useWithFilters();
  const slug = pathname.replace(/^\//, "").split("/")[0];
  const page = findPage(slug);
  const section = findSection(slug);

  if (!page || !section) return null;

  const space = findProductSpace(slug);
  // La sección sólo aporta un nivel propio cuando no repite el nombre de sus
  // vecinos: ni "Investigador › Investigador" (sección = página) ni
  // "Mercado › Mercado › Organos" (sección = espacio) informan de nada.
  const showSection = section.label !== page.label && section.label !== space?.label;

  return (
    <nav
      aria-label="Ruta de navegación"
      className="flex items-center gap-1.5 px-4 py-2 text-sm text-muted-foreground"
    >
      {space && (
        <>
          <Link
            href={withFilters(`/${space.slug}`)}
            className="transition-colors hover:text-foreground"
          >
            {space.label}
          </Link>
          <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
        </>
      )}
      {showSection && (
        <>
          <Link
            href={withFilters(`/${section.pages[0].slug}`)}
            className="transition-colors hover:text-foreground"
          >
            {section.label}
          </Link>
          <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
        </>
      )}
      <span className="font-medium text-foreground">{page.label}</span>
    </nav>
  );
}
