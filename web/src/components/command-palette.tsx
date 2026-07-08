/**
 * Command palette (⌘K) — power-user launcher.
 *
 * Built on the cmdk primitive inside a self-managed overlay. Provides:
 *  - navigation to every dashboard route (admin routes gated by role),
 *  - "jump to licitación by id" when the query looks like an id,
 *  - free-text search handoff to /detalle when it doesn't look like an id,
 *  - quick actions: open copilot, toggle theme, toggle density.
 *
 * Visibility is driven by the shared UI store so keyboard shortcuts, the hero
 * ask-bar and the top-nav can all open it.
 */
"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { Command } from "cmdk";
import { toast } from "sonner";
import {
  ArrowRight,
  AlignJustify,
  Bookmark,
  FileSpreadsheet,
  FileText,
  LayoutGrid,
  Link2,
  Moon,
  Search,
  Sparkles,
  Star,
  Sun,
} from "lucide-react";
import { SECTIONS } from "@/lib/navigation";
import { useUiStore } from "@/lib/ui-store";
import { useAdmin } from "@/hooks/use-admin";
import { useDensity } from "@/lib/density";
import { useFilterParams, useWithFilters } from "@/lib/filters";
import { buildExportUrl, triggerDownload } from "@/lib/export";

/** Heuristic: a token with a digit and id-like separators is probably a tender id. */
function looksLikeLicitacionId(value: string): boolean {
  const v = value.trim();
  return v.length >= 4 && /\d/.test(v) && /^[A-Za-z0-9][A-Za-z0-9\-_/.]+$/.test(v);
}

export function CommandPalette() {
  const open = useUiStore((s) => s.commandOpen);
  // Mount the palette only while open so each launch starts with a clean query
  // (no reset effect needed) and focus management runs on a fresh mount.
  if (!open) return null;
  return <CommandPaletteInner />;
}

function CommandPaletteInner() {
  const setOpen = useUiStore((s) => s.setCommandOpen);
  const openCopilot = useUiStore((s) => s.openCopilot);
  const openSavedViews = useUiStore((s) => s.openSavedViews);
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  const { compact, toggleCompact } = useDensity();
  const isAdmin = useAdmin();
  const withFilters = useWithFilters();
  const filterParams = useFilterParams();
  const [search, setSearch] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement>(null);

  // Focus the search field when the palette opens (a11y-friendly vs. autoFocus).
  React.useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const run = React.useCallback(
    (action: () => void) => {
      setOpen(false);
      action();
    },
    [setOpen],
  );

  const visibleSections = SECTIONS.filter((s) => !s.adminOnly || isAdmin);
  const idQuery = search.trim();
  const showJump = looksLikeLicitacionId(idQuery);
  const showSearch = idQuery.length >= 2 && !showJump;
  const hasActiveFilters = Object.keys(filterParams).length > 0;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center p-4 pt-[12vh] sm:pt-[18vh]"
      role="dialog"
      aria-modal="true"
      aria-label="Paleta de comandos"
    >
      <button
        type="button"
        aria-label="Cerrar paleta de comandos"
        className="absolute inset-0 bg-black/40 backdrop-blur-sm motion-safe:animate-in motion-safe:fade-in"
        onClick={() => setOpen(false)}
      />
      <Command
        label="Paleta de comandos"
        className="tf-glass-strong relative z-10 w-full max-w-xl overflow-hidden rounded-xl border border-border/70 shadow-2xl motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-95"
        loop
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            setOpen(false);
          }
        }}
      >
        <div className="flex items-center gap-2 border-b border-border/60 px-3">
          <Sparkles className="h-4 w-4 shrink-0 text-primary" />
          <Command.Input
            ref={inputRef}
            value={search}
            onValueChange={setSearch}
            placeholder="Buscar páginas, acciones o id de licitación…"
            className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          <kbd className="hidden rounded border border-border/70 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground sm:inline">
            Esc
          </kbd>
        </div>

        <Command.List className="max-h-[min(60vh,420px)] overflow-y-auto p-2">
          <Command.Empty className="py-6 text-center text-sm text-muted-foreground">
            Sin resultados.
          </Command.Empty>

          {(showJump || showSearch) && (
            <Command.Group
              heading="Saltar a"
              className="px-1 text-[11px] font-medium text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
            >
              {showJump && (
                <Command.Item
                  value={`licitacion ${idQuery}`}
                  onSelect={() =>
                    run(() => router.push(`/detalle?lic=${encodeURIComponent(idQuery)}`))
                  }
                  className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm aria-selected:bg-accent aria-selected:text-accent-foreground"
                >
                  <ArrowRight className="h-4 w-4 text-primary" />
                  Ir a licitación <span className="font-mono text-xs">{idQuery}</span>
                </Command.Item>
              )}
              {showSearch && (
                <Command.Item
                  value={`buscar ${idQuery}`}
                  onSelect={() =>
                    run(() => router.push(`/detalle?q=${encodeURIComponent(idQuery)}`))
                  }
                  className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm aria-selected:bg-accent aria-selected:text-accent-foreground"
                >
                  <Search className="h-4 w-4 text-primary" />
                  Buscar <span className="font-mono text-xs">&quot;{idQuery}&quot;</span> en licitaciones
                </Command.Item>
              )}
            </Command.Group>
          )}

          <Command.Group
            heading="Acciones"
            className="px-1 text-[11px] font-medium text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
          >
            <Command.Item
              value="copiloto preguntar ask ia"
              onSelect={() => run(() => openCopilot())}
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm aria-selected:bg-accent aria-selected:text-accent-foreground"
            >
              <Sparkles className="h-4 w-4 text-primary" />
              Abrir copiloto
            </Command.Item>
            <Command.Item
              value="tema theme oscuro claro dark light"
              onSelect={() =>
                run(() => setTheme(theme === "dark" ? "light" : "dark"))
              }
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm aria-selected:bg-accent aria-selected:text-accent-foreground"
            >
              {theme === "dark" ? (
                <Sun className="h-4 w-4" />
              ) : (
                <Moon className="h-4 w-4" />
              )}
              Cambiar tema ({theme === "dark" ? "claro" : "oscuro"})
            </Command.Item>
            <Command.Item
              value="densidad compacta normal density"
              onSelect={() => run(() => toggleCompact())}
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm aria-selected:bg-accent aria-selected:text-accent-foreground"
            >
              {compact ? (
                <LayoutGrid className="h-4 w-4" />
              ) : (
                <AlignJustify className="h-4 w-4" />
              )}
              Densidad {compact ? "normal" : "compacta"}
            </Command.Item>
          </Command.Group>

          {hasActiveFilters && (
            <Command.Group
              heading="Acciones con filtros"
              className="px-1 text-[11px] font-medium text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
            >
              <Command.Item
                value="guardar vista actual saved view"
                onSelect={() => run(() => openSavedViews())}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm aria-selected:bg-accent aria-selected:text-accent-foreground"
              >
                <Bookmark className="h-4 w-4 text-primary" />
                Guardar vista actual
              </Command.Item>
              <Command.Item
                value="crear regla watchlist alerta filtros"
                onSelect={() =>
                  run(() =>
                    router.push(
                      `/mi-watchlist?prefill=${encodeURIComponent(JSON.stringify(filterParams))}`,
                    ),
                  )
                }
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm aria-selected:bg-accent aria-selected:text-accent-foreground"
              >
                <Star className="h-4 w-4 text-primary" />
                Crear regla de watchlist con estos filtros
              </Command.Item>
              <Command.Item
                value="exportar csv vista actual"
                onSelect={() =>
                  run(() =>
                    triggerDownload(
                      buildExportUrl("/api/v1/exports/download", "csv", filterParams),
                    ),
                  )
                }
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm aria-selected:bg-accent aria-selected:text-accent-foreground"
              >
                <FileText className="h-4 w-4 text-primary" />
                Exportar CSV (vista actual)
              </Command.Item>
              <Command.Item
                value="exportar excel xlsx vista actual"
                onSelect={() =>
                  run(() =>
                    triggerDownload(
                      buildExportUrl("/api/v1/exports/download", "xlsx", filterParams),
                    ),
                  )
                }
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm aria-selected:bg-accent aria-selected:text-accent-foreground"
              >
                <FileSpreadsheet className="h-4 w-4 text-primary" />
                Exportar Excel (vista actual)
              </Command.Item>
              <Command.Item
                value="copiar enlace con filtros link"
                onSelect={() =>
                  run(() => {
                    navigator.clipboard.writeText(window.location.href);
                    toast.success("Enlace copiado");
                  })
                }
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm aria-selected:bg-accent aria-selected:text-accent-foreground"
              >
                <Link2 className="h-4 w-4 text-primary" />
                Copiar enlace con filtros
              </Command.Item>
            </Command.Group>
          )}

          {visibleSections.map((section) => (
            <Command.Group
              key={section.label}
              heading={section.label}
              className="px-1 text-[11px] font-medium text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
            >
              {section.pages.map((page) => {
                const Icon = page.icon;
                return (
                  <Command.Item
                    key={page.slug}
                    value={`${page.label} ${page.description}`}
                    onSelect={() => run(() => router.push(withFilters(`/${page.slug}`)))}
                    className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm aria-selected:bg-accent aria-selected:text-accent-foreground"
                  >
                    <Icon className="h-4 w-4 text-muted-foreground" />
                    {page.label}
                  </Command.Item>
                );
              })}
            </Command.Group>
          ))}
        </Command.List>
      </Command>
    </div>
  );
}
