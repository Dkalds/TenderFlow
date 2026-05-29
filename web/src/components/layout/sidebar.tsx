"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { findSection, type NavSection } from "@/lib/navigation";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = React.useState(false);

  const slug = pathname.replace("/", "");
  const section: NavSection | undefined = findSection(slug);

  if (!section) return null;

  return (
    <aside
      className={cn(
        "hidden md:flex flex-col border-r bg-background transition-all duration-200 shrink-0",
        collapsed ? "w-16" : "w-64"
      )}
    >
      {/* Section header */}
      <div className="flex items-center justify-between p-3 border-b">
        {!collapsed && (
          <span className="text-sm font-semibold truncate">
            {section.label}
          </span>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? (
            <PanelLeftOpen className="h-4 w-4" />
          ) : (
            <PanelLeftClose className="h-4 w-4" />
          )}
          <span className="sr-only">
            {collapsed ? "Expand sidebar" : "Collapse sidebar"}
          </span>
        </Button>
      </div>

      {/* Page links */}
      <nav className="flex-1 p-2 space-y-0.5 overflow-y-auto">
        {section.pages.map((page) => {
          const Icon = page.icon;
          const active = pathname === `/${page.slug}`;
          return (
            <Link
              key={page.slug}
              href={`/${page.slug}`}
              title={collapsed ? page.label : undefined}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-primary/10 text-primary font-medium border-l-2 border-primary"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent",
                collapsed && "justify-center px-0"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span className="truncate">{page.label}</span>}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
