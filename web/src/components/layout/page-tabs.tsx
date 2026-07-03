"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { findSection } from "@/lib/navigation";
import { useWithFilters } from "@/lib/filters";
import { cn } from "@/lib/utils";

/**
 * Row of tabs for sibling pages within the same sidebar group.
 *
 * The sidebar now links to one entry per group (see `sidebar.tsx`); when a
 * group has more than one page, this component renders the sibling pages as
 * tabs above the content area so every page keeps its own stable, bookmarkable
 * URL while staying reachable without going back to the sidebar.
 */
export function PageTabs() {
  const pathname = usePathname();
  const withFilters = useWithFilters();
  const slug = pathname.replace(/^\//, "").split("/")[0];
  const section = findSection(slug);

  if (!section || section.pages.length <= 1) return null;

  return (
    <nav
      aria-label={`Paginas de ${section.label}`}
      className="flex items-center gap-1 border-b border-border/70 px-1"
    >
      {section.pages.map((page) => {
        const active = pathname === `/${page.slug}`;
        return (
          <Link
            key={page.slug}
            href={withFilters(`/${page.slug}`)}
            aria-current={active ? "page" : undefined}
            className={cn(
              "relative px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "text-foreground after:absolute after:inset-x-3 after:-bottom-px after:h-0.5 after:rounded-full after:bg-primary"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {page.label}
          </Link>
        );
      })}
    </nav>
  );
}
