"use client";

import { Toaster as SonnerToaster, type ToasterProps } from "sonner";
import { useTheme } from "next-themes";
import { CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";

/**
 * Iconos de contorno del mismo juego que `Aviso` y `PanelError`, con el color
 * del tipo. Sustituyen a los discos rellenos de Sonner.
 */
const ICONOS: ToasterProps["icons"] = {
  success: <CircleCheck className="text-success h-4 w-4" aria-hidden="true" />,
  error: <CircleAlert className="text-destructive h-4 w-4" aria-hidden="true" />,
  warning: <TriangleAlert className="text-warning h-4 w-4" aria-hidden="true" />,
  info: <Info className="text-info h-4 w-4" aria-hidden="true" />,
};

/**
 * `<Toaster />` de Sonner con el tema y la superficie de la app.
 *
 * Tema: Sonner usa `theme="light"` si no se le dice otra cosa, pero el de la
 * app lo resuelve next-themes (`defaultTheme="system"`): sin esto, los toasts
 * salían como una tarjeta clara sobre la UI oscura. `resolvedTheme` y no
 * `theme`, que con el valor por defecto es literalmente "system".
 *
 * Sin `richColors`: las cajas pastel roja, verde y ámbar son la demo de Sonner,
 * no el idioma de la app. El toast es la tarjeta de la app, y el tipo lo dicen
 * la forma y el color del icono, como en `Aviso`.
 *
 * La piel (fondo, borde y texto desde los tokens, sombra, radio, fuente,
 * descripción en gris y foco) vive en `globals.css`, no en
 * `toastOptions.classNames`: la hoja que Sonner inyecta va sin capa y gana a
 * cualquier utilidad de Tailwind, que viven en `@layer utilities`.
 */
export function Toaster() {
  const { resolvedTheme } = useTheme();
  return <SonnerToaster theme={resolvedTheme === "light" ? "light" : "dark"} position="bottom-right" icons={ICONOS} />;
}
