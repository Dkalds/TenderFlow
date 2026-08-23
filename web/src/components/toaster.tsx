"use client";

import { Toaster as SonnerToaster } from "sonner";
import { useTheme } from "next-themes";

/**
 * Theme-aware wrapper around Sonner's `<Toaster />`. Sonner defaults to
 * `theme="light"` when unset, but the app's theme is resolved by next-themes
 * (`ThemeProvider defaultTheme="system"` in providers.tsx) — without this,
 * toasts render as a light card floating over a dark UI. `resolvedTheme` and
 * not `theme`: with the system default, `theme` is the literal string
 * "system" until the user picks one. Sonner is Emil Kowalski's own toast
 * library and "good defaults matter more than options" is its own stated
 * principle (emil-design-eng, Sonner principles), so this just makes the
 * default actually match the app.
 */
export function Toaster() {
  const { resolvedTheme } = useTheme();
  return <SonnerToaster theme={resolvedTheme === "light" ? "light" : "dark"} richColors position="bottom-right" />;
}
