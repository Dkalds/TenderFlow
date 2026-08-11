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
import {
  isSpaceVisible,
  CONSOLE_GROUP_ORDER,
  CONSOLE_SPACES,
  type ConsoleGroup,
} from "@/lib/console-spaces";

/** Encabezados de los grupos del rail, en la paleta. */
const GROUP_LABELS: Record<ConsoleGroup, string> = {
  trabajo: "Trabajo diario",
  analisis: "Análisis",
  personal: "Mi seguimiento",
  organizacion: "Organización",
};
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

  // Un grupo por familia de espacios; cada espacio multivista despliega sus
  // vistas como destinos propios.
  const spaceGroups = React.useMemo(() => {
    const spaces = CONSOLE_SPACES.filter((space) => isSpaceVisible(space, isAdmin));
    return CONSOLE_GROUP_ORDER.map((group) => ({
      label: GROUP_LABELS[group],
      items: spaces
        .filter((space) => space.group === group)
        .flatMap((space) => {
          const base = {
            icon: space.icon,
            href: `/${space.slug}`,
            label: space.label,
            value: `${space.label} ${space.description}`,
            hint: undefined as string | undefined,
          };
          if (!space.views || space.views.length < 2) return [base];
          return [
            base,
            ...space.views.map((view) => ({
              icon: space.icon,
              href: `/${space.slug}?vista=${view.key}`,
              label: view.label,
              value: `${space.label} ${view.label}${view.from ? ` /${view.from}` : ""}`,
              hint: space.label as string | undefined,
            })),
          ];
        }),
    })).filter((group) => group.items.length > 0);
  }, [isAdmin]);
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
        // Sin animación a propósito: toggle vía atajo de teclado (⌘K), acción
        // de alta frecuencia para power users. Raycast/Spotlight no animan su
        // apertura y esa es la referencia (find-animation-opportunities).
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={() => setOpen(false)}
      />
      <Command
        label="Paleta de comandos"
        className="tf-glass-strong relative z-10 w-full max-w-xl overflow-hidden rounded-xl border border-border/70 shadow-2xl"
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

          {/* Destinos: los espacios de la consola, no las rutas heredadas. Cada
              vista es su propia entrada, así que ⌘K salta directo al corte
              (`/mercado?vista=geografia`) en vez de pasar por un redirect. */}
          {spaceGroups.map((group) => (
            <Command.Group
              key={group.label}
              heading={group.label}
              className="px-1 text-[11px] font-medium text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
            >
              {group.items.map((item) => {
                const Icon = item.icon;
                return (
                  <Command.Item
                    key={item.href}
                    value={item.value}
                    onSelect={() => run(() => router.push(withFilters(item.href)))}
                    className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm aria-selected:bg-accent aria-selected:text-accent-foreground"
                  >
                    <Icon className="h-4 w-4 text-muted-foreground" />
                    {item.label}
                    {item.hint && (
                      <span className="ml-auto text-[11px] text-muted-foreground">{item.hint}</span>
                    )}
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
