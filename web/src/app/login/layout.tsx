import type { Metadata } from "next";

/**
 * Los metadatos de `/login` viven en un layout y no en la página porque
 * `login/page.tsx` es un Client Component (usa `useSearchParams` para el
 * `?redirect=` y el estado del formulario) y un `"use client"` no puede
 * exportar `metadata`.
 *
 * El `canonical` es lo que aporta valor real aquí: sin sesión, el middleware
 * manda a `/login?redirect=<ruta>` desde **cada** ruta del dashboard, y a eso
 * se suman `?error=` del callback de Google y `?mfa=required`. Son decenas de
 * URLs distintas con el mismo contenido; el canonical las colapsa en una.
 *
 * `noindex` es redundante con el default de `app/layout.tsx`, y es a propósito:
 * cuando exista el grupo público que revierta ese default, la pantalla de login
 * no debe depender de que alguien se acuerde de excluirla.
 */
export const metadata: Metadata = {
  title: "Iniciar sesión",
  description:
    "Accede a tu cuenta de TenderFlow para consultar licitaciones, pipeline y análisis competitivo.",
  robots: { index: false, follow: false },
  alternates: { canonical: "/login" },
};

export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return children;
}
