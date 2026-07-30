"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { findPage, findProductSpace } from "@/lib/navigation";
import { useWithFilters } from "@/lib/filters";

export function Breadcrumb() {
  const pathname = usePathname();
  const withFilters = useWithFilters();
  const slug = pathname.replace(/^\//, "").split("/")[0];
  const space = findProductSpace(slug);
  const page = findPage(slug);

  if (!space || !page) return null;

  const spaceHref = withFilters(`/${space.slug}`);

  return (
    <nav className="flex items-center gap-1.5 text-sm text-muted-foreground px-4 py-2">
      <Link
        href={spaceHref}
        className="hover:text-foreground transition-colors"
      >
        {space.label}
      </Link>
      <ChevronRight className="h-3.5 w-3.5" />
      <span className="text-foreground font-medium">{page.label}</span>
    </nav>
  );
}
