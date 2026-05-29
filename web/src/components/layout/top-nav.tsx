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
  ChevronDown,
} from "lucide-react";
import { SECTIONS } from "@/lib/navigation";
import { t, getLocale, setLocale, type Locale } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

function sectionHref(sectionIndex: number): string {
  return `/${SECTIONS[sectionIndex].pages[0].slug}`;
}

function isActiveSection(pathname: string, sectionIndex: number): boolean {
  const section = SECTIONS[sectionIndex];
  return section.pages.some((p) => pathname === `/${p.slug}`);
}

export function TopNav() {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [userMenuOpen, setUserMenuOpen] = React.useState(false);
  const [locale, setLocaleState] = React.useState<Locale>(getLocale());

  const toggleTheme = () => setTheme(theme === "dark" ? "light" : "dark");

  const toggleLocale = () => {
    const next: Locale = locale === "es" ? "en" : "es";
    setLocale(next);
    setLocaleState(next);
  };

  return (
    <>
      <header className="fixed top-0 left-0 right-0 z-50 h-14 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="flex h-full items-center px-4 gap-4">
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

          {/* Logo / Title */}
          <Link
            href="/"
            className="flex items-center gap-2 font-semibold text-lg shrink-0"
          >
            {t("app.title")}
          </Link>

          {/* Section tabs — desktop */}
          <nav className="hidden md:flex items-center gap-1 mx-auto">
            {SECTIONS.map((section, i) => {
              const Icon = section.icon;
              const active = isActiveSection(pathname, i);
              return (
                <Link
                  key={section.label}
                  href={sectionHref(i)}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                    active
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:text-foreground hover:bg-accent"
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {section.label}
                </Link>
              );
            })}
          </nav>

          {/* Right side actions */}
          <div className="flex items-center gap-1 ml-auto md:ml-0">
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
            >
              <Globe className="h-4 w-4" />
              {locale.toUpperCase()}
            </Button>

            {/* User menu */}
            <div className="relative">
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setUserMenuOpen(!userMenuOpen)}
              >
                <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-medium">
                  <User className="h-4 w-4" />
                </div>
              </Button>
              {userMenuOpen && (
                <div className="absolute right-0 top-full mt-1 w-48 rounded-md border bg-popover p-1 shadow-md">
                  <button className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm hover:bg-accent">
                    <User className="h-4 w-4" />
                    Perfil
                  </button>
                  <button className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm hover:bg-accent text-destructive">
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
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setMobileOpen(false)}
          />
          <nav className="absolute left-0 top-14 bottom-0 w-72 bg-background border-r p-4 space-y-1 overflow-y-auto">
            {SECTIONS.map((section, i) => {
              const Icon = section.icon;
              const active = isActiveSection(pathname, i);
              return (
                <div key={section.label}>
                  <Link
                    href={sectionHref(i)}
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
                              "flex items-center gap-2 px-3 py-1.5 rounded-md text-sm transition-colors",
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
