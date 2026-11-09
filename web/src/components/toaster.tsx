"use client";

import dynamic from "next/dynamic";

/**
 * El `Toaster` de las superficies con sesión, fuera del First Load.
 *
 * Sonner (34,5 KB) viajaba en la carga inicial de toda pantalla con sesión
 * porque este componente va en la pila común (`superficie-privada.tsx`). Ahora
 * se pide al hidratar: el HTML del servidor no pintaba nada suyo (sin avisos,
 * Sonner no dibuja la lista), y un `toast()` que llegue antes no se pierde
 * (`lib/toast.ts`). La piel y los iconos viven en `toaster-sonner.tsx`.
 */
export const Toaster = dynamic(() => import("@/components/toaster-sonner").then((modulo) => modulo.Toaster), {
  ssr: false,
});
