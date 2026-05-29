"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { findPage, findSection } from "@/lib/navigation";

export function Breadcrumb() {
  const pathname = usePathname();
  const slug = pathname.replace("/", "");
  const section = findSection(slug);
  const page = findPage(slug);

  if (!section || !page) return null;

  const sectionHref = `/${section.pages[0].slug}`;

  return (
    <nav className="flex items-center gap-1.5 text-sm text-muted-foreground px-4 py-2">
      <Link
        href={sectionHref}
        className="hover:text-foreground transition-colors"
      >
        {section.label}
      </Link>
      <ChevronRight className="h-3.5 w-3.5" />
      <span className="text-foreground font-medium">{page.label}</span>
    </nav>
  );
}
