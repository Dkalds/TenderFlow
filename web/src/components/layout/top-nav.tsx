"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import {
  Menu,
  Moon,
  Sun,
  Globe,
  User,
  LogOut,
  AlignJustify,
  LayoutGrid,
  Search,
} from "lucide-react";
import { TenderFlowLogo } from "@/components/layout/tenderflow-logo";
import { SECTIONS } from "@/lib/navigation";
import { t, getLocale, setLocale, type Locale } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NotificationBell } from "@/components/notification-bell";
import { ExportPopover } from "@/components/export-popover";
import { useDensity, initDensity } from "@/lib/density";
import { useAdmin } from "@/hooks/use-admin";
import { useFilters } from "@/lib/filters";
import { apiMutate } from "@/lib/api-client";

export function TopNav() {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [userMenuOpen, setUserMenuOpen] = React.useState(false);
  const [locale, setLocaleState] = React.useState<Locale>(getLocale());
  const userMenuTriggerRef = React.useRef<HTMLButtonElement>(null);
  const { q, setQ } = useFilters();

  const handleLogout = async () => {
    try {
      await apiMutate("POST", "/api/v1/auth/logout");
    } catch {
      // Even if the API call fails, redirect to login
    }
    window.location.href = "/login";
  };

  const toggleTheme = () => setTheme(theme === "dark" ? "light" : "dark");
  const { compact, toggleCompact } = useDensity();
  const isAdmin = useAdmin();

  React.useEffect(() => { initDensity(); }, []);

  const visibleSections = SECTIONS.filter(
    (s) => !s.adminOnly || isAdmin,
  );

  const toggleLocale = () => {
    const next: Locale = locale === "es" ? "en" : "es";
    setLocale(next);
    setLocaleState(next);
  };

  return (
    <>
      <header className="sticky top-0 z-40 h-[60px] border-b border-border/70 bg-background/90 backdrop-blur supports-[backdrop-filter]:bg-background/75">
        <div className="flex h-full items-center gap-3 px-4">
          {/* Mobile hamburger */}
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            onClick={() => setMobileOpen(!mobileOpen)}
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

          <div className="relative hidden min-w-72 max-w-xl flex-1 md:block">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              data-search-input
              aria-label="Busqueda global"
              className="h-9 rounded-lg border-border/70 bg-card/80 pl-9 pr-12 text-sm"
              placeholder="Buscar licitaciones, organos, empresas..."
              value={q}
              onChange={(event) => setQ(event.target.value)}
            />
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 rounded border border-border/70 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">Ctrl K</span>
          </div>

          <span className="hidden items-center gap-2 rounded-full border border-border/70 px-3 py-1 text-[11px] text-muted-foreground lg:inline-flex">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
            </span>
            Datos en vivo
          </span>

          {/* Right side actions */}
          <div className="ml-auto flex items-center gap-1 md:ml-0">
            {/* Export */}
            <ExportPopover />

            {/* Notifications */}
            <NotificationBell />

            {/* Density toggle */}
            <Button variant="ghost" size="icon" onClick={toggleCompact} title={compact ? "Normal density" : "Compact density"}>
              {compact ? <LayoutGrid className="h-4 w-4" /> : <AlignJustify className="h-4 w-4" />}
              <span className="sr-only">Toggle density</span>
            </Button>

            {/* Theme toggle */}
            <Button variant="ghost" size="icon" onClick={toggleTheme}>
              <Sun className="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
              <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
              <span className="sr-only">Toggle theme</span>
            </Button>

            {/* Locale toggle */}
            <Button
              variant="ghost"
              size="sm"
              onClick={toggleLocale}
              className="gap-1 text-xs"
              aria-label="Cambiar idioma"
            >
              <Globe className="h-4 w-4" />
              {locale.toUpperCase()}
            </Button>

            {/* User menu */}
            <div className="relative">
              <Button
                ref={userMenuTriggerRef}
                variant="ghost"
                size="icon"
                onClick={() => setUserMenuOpen(!userMenuOpen)}
                aria-label="Menú de usuario"
                aria-expanded={userMenuOpen}
              >
                <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-medium">
                  <User className="h-4 w-4" />
                </div>
              </Button>
              {userMenuOpen && (
                <div
                  className="absolute right-0 top-full mt-1 w-48 rounded-md border bg-popover p-1 shadow-md"
                  role="menu"
                  onKeyDown={(e) => {
                    if (e.key === "Escape") {
                      setUserMenuOpen(false);
                      userMenuTriggerRef.current?.focus();
                    }
                  }}
                >
                  <button role="menuitem" className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm hover:bg-accent">
                    <User className="h-4 w-4" />
                    Perfil
                  </button>
                  <button role="menuitem" onClick={handleLogout} className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm hover:bg-accent text-destructive">
                    <LogOut className="h-4 w-4" />
                    {t("auth.logout")}
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Mobile sheet */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 md:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Menú de navegación"
          onKeyDown={(e) => { if (e.key === "Escape") setMobileOpen(false); }}
        >
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setMobileOpen(false)}
          />
          <nav className="absolute left-0 top-14 bottom-0 w-72 bg-background border-r p-4 space-y-1 overflow-y-auto" aria-label="Navegación móvil">
            {visibleSections.map((section) => {
              const Icon = section.icon;
              const active = section.pages.some((p) => pathname === `/${p.slug}`);
              return (
                <div key={section.label}>
                  <Link
                    href={`/${section.pages[0].slug}`}
                    onClick={() => setMobileOpen(false)}
                    className={cn(
                      "flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors",
                      active
                        ? "bg-primary/10 text-primary"
                        : "text-muted-foreground hover:text-foreground hover:bg-accent"
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    {section.label}
                  </Link>
                  {active && (
                    <div className="ml-4 mt-1 space-y-0.5">
                      {section.pages.map((page) => {
                        const PageIcon = page.icon;
                        const pageActive = pathname === `/${page.slug}`;
                        return (
                          <Link
                            key={page.slug}
                            href={`/${page.slug}`}
                            onClick={() => setMobileOpen(false)}
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
        </div>
      )}
    </>
  );
}
