"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import {
  Menu,
  Moon,
  Sun,
  User,
  LogOut,
  AlignJustify,
  LayoutGrid,
  Search,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { TenderFlowLogo } from "@/components/layout/tenderflow-logo";
import { SECTIONS } from "@/lib/navigation";
import { t } from "@/lib/i18n";
import { cn, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { NotificationBell } from "@/components/notification-bell";
import { ExportPopover } from "@/components/export-popover";
import { useDensity, initDensity } from "@/lib/density";
import { useAdmin } from "@/hooks/use-admin";
import { useDataFreshness } from "@/hooks/use-data-freshness";
import { useWithFilters } from "@/lib/filters";
import { useUiStore } from "@/lib/ui-store";
import { apiMutate } from "@/lib/api-client";
import { reportError } from "@/lib/report-error";

export function TopNav() {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [expandedSection, setExpandedSection] = React.useState<string | null>(null);
  const withFilters = useWithFilters();
  const setCommandOpen = useUiStore((s) => s.setCommandOpen);

  const handleLogout = async () => {
    try {
      await apiMutate("POST", "/api/v1/auth/logout");
    } catch (err) {
      reportError("TopNav.logout", err);
    }
    window.location.href = "/login";
  };

  const toggleTheme = () => setTheme(theme === "dark" ? "light" : "dark");
  const { compact, toggleCompact } = useDensity();
  const isAdmin = useAdmin();

  React.useEffect(() => { initDensity(); }, []);

  // Frescura del dato: un solo hook compartido con la sidebar. Antes cada uno
  // consultaba un endpoint distinto (`meta/last-extraction` aquí,
  // `analytics/quality` allí) y podían mostrar antigüedades que no cuadraban.
  const { lastExtraction, relative } = useDataFreshness();

  const visibleSections = SECTIONS.filter(
    (s) => !s.adminOnly || isAdmin,
  );

  // Auto-expand the section containing the active page whenever the mobile
  // drawer is opened, so the user isn't forced to reopen it to find it.
  const openMobileNav = () => {
    const activeSection = visibleSections.find((section) =>
      section.pages.some((p) => pathname === `/${p.slug}`),
    );
    setExpandedSection(activeSection?.label ?? null);
    setMobileOpen(true);
  };

  return (
    <>
      <header className="tf-glass sticky top-0 z-40 h-[60px] border-b border-border/70">
        <div className="flex h-full items-center gap-3 px-4">
          {/* Mobile hamburger */}
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            onClick={() => (mobileOpen ? setMobileOpen(false) : openMobileNav())}
            aria-expanded={mobileOpen}
            aria-label={mobileOpen ? "Cerrar menu" : "Abrir menu"}
          >
            <Menu className="h-5 w-5" />
            <span className="sr-only">Menu</span>
          </Button>

          {/* Logo / Title for mobile, full brand lives in sidebar on desktop */}
          <Link
            href="/"
            className="flex shrink-0 items-center gap-2 md:hidden"
          >
            <TenderFlowLogo boxSize={32} />
          </Link>

          {/* La busqueda unica vive en la barra de filtros (por pagina) y en
              la command palette; este boton solo abre la paleta — evita dos
              buscadores ligados al mismo `q` visibles a la vez. */}
          <button
            type="button"
            onClick={() => setCommandOpen(true)}
            aria-label="Abrir busqueda y comandos"
            className="hidden min-w-72 max-w-xl flex-1 items-center gap-2 rounded-lg border border-border/70 bg-card/80 px-3 h-9 text-sm text-muted-foreground transition-colors hover:border-border hover:text-foreground md:flex"
          >
            <Search className="h-4 w-4 shrink-0" />
            <span className="flex-1 text-left truncate">Buscar licitaciones, organos, empresas...</span>
            <span className="rounded border border-border/70 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
              Ctrl K
            </span>
          </button>

          {/* Right side actions */}
          <div className="ml-auto flex items-center gap-1">
            {/* Indicador de estado, no un control: el instante exacto viaja en
                el nombre accesible en vez de esconderse tras un `title=` nativo
                (que no se dispara con teclado) o tras un tooltip colgado de un
                `<span tabIndex={0}>` que fingiría ser interactivo. */}
            <span className="hidden items-center gap-1.5 rounded-full border border-border/70 px-3 py-1 text-[11px] text-muted-foreground lg:inline-flex">
              <span className="relative flex h-2 w-2" aria-hidden="true">
                <span className="absolute inline-flex h-full w-full motion-safe:animate-ping rounded-full bg-primary opacity-60" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
              </span>
              <span aria-hidden="true">Datos en vivo</span>
              {relative && (
                <>
                  <span className="opacity-40" aria-hidden="true">·</span>
                  <span className="text-[10px] opacity-60" aria-hidden="true">{relative}</span>
                </>
              )}
              <span className="sr-only">
                {lastExtraction
                  ? `Datos en vivo. Última extracción: ${formatDate(lastExtraction)}.`
                  : "Datos en vivo. Todavía sin registro de extracción."}
              </span>
            </span>

            {/* Export */}
            <ExportPopover />

            {/* Notifications */}
            <NotificationBell />

            {/* Density toggle */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" onClick={toggleCompact}>
                  {compact ? <LayoutGrid className="h-4 w-4" /> : <AlignJustify className="h-4 w-4" />}
                  <span className="sr-only">Toggle density</span>
                </Button>
              </TooltipTrigger>
              <TooltipContent>{compact ? "Normal density" : "Compact density"}</TooltipContent>
            </Tooltip>

            {/* Theme toggle */}
            <span className="mx-1 hidden h-5 w-px bg-border/70 sm:block" aria-hidden="true" />
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" onClick={toggleTheme}>
                  <Sun className="h-4 w-4 rotate-0 scale-100 transition-transform dark:-rotate-90 dark:scale-0" />
                  <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-transform dark:rotate-0 dark:scale-100" />
                  <span className="sr-only">Toggle theme</span>
                </Button>
              </TooltipTrigger>
              <TooltipContent>{theme === "dark" ? "Light mode" : "Dark mode"}</TooltipContent>
            </Tooltip>

            {/* User menu */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label="Menú de usuario">
                  <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-medium">
                    <User className="h-4 w-4" />
                  </div>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <DropdownMenuItem>
                  <User className="h-4 w-4" />
                  Perfil
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => handleLogout()}
                  className="text-destructive focus:text-destructive"
                >
                  <LogOut className="h-4 w-4" />
                  {t("auth.logout")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>

      {/* Mobile sheet — same primitive as the desktop Sheet (CopilotPanel,
          DetailPanel, …), so it gets a real exit animation, focus trap, and
          scroll lock for free instead of the hand-rolled version's
          enter-only teleport-on-close. */}
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent side="left" className="w-72 overflow-y-auto p-4 md:hidden">
          <SheetTitle className="sr-only">Menú de navegación</SheetTitle>
          <nav className="space-y-1" aria-label="Navegación móvil">
            {visibleSections.map((section) => {
              const Icon = section.icon;
              const active = section.pages.some((p) => pathname === `/${p.slug}`);
              const expanded = expandedSection === section.label;
              const sectionPanelId = `mobile-nav-section-${section.label.replace(/\s+/g, "-").toLowerCase()}`;
              return (
                <div key={section.label}>
                  <button
                    type="button"
                    onClick={() =>
                      setExpandedSection(expanded ? null : section.label)
                    }
                    aria-expanded={expanded}
                    aria-controls={sectionPanelId}
                    className={cn(
                      "flex w-full items-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors",
                      active
                        ? "bg-primary/10 text-primary"
                        : "text-muted-foreground hover:text-foreground hover:bg-accent"
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    <span className="flex-1 text-left">{section.label}</span>
                    {expanded ? (
                      <ChevronDown className="h-4 w-4 shrink-0" />
                    ) : (
                      <ChevronRight className="h-4 w-4 shrink-0" />
                    )}
                  </button>
                  {expanded && (
                    <div id={sectionPanelId} className="ml-4 mt-1 space-y-0.5">
                      {section.pages.map((page) => {
                        const PageIcon = page.icon;
                        const pageActive = pathname === `/${page.slug}`;
                        return (
                          <Link
                            key={page.slug}
                            href={withFilters(`/${page.slug}`)}
                            onClick={() => setMobileOpen(false)}
                            aria-current={pageActive ? "page" : undefined}
                            className={cn(
                              "flex items-center gap-2 px-3 py-2.5 rounded-md text-sm transition-colors",
                              pageActive
                                ? "text-primary font-medium"
                                : "text-muted-foreground hover:text-foreground"
                            )}
                          >
                            <PageIcon className="h-3.5 w-3.5" />
                            {page.label}
                          </Link>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </nav>
        </SheetContent>
      </Sheet>
    </>
  );
}
