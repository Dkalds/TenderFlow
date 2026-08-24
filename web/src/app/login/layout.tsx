import type { Metadata } from "next";
import { headers } from "next/headers";
import { Providers } from "@/components/providers";
import { RouteProgress } from "@/components/route-progress";
import { Toaster } from "@/components/toaster";
import { LiveRegion } from "@/components/live-region";

/**
 * Los metadatos de `/login` viven en un layout y no en la página porque
 * `login/page.tsx` es un Client Component (usa `useSearchParams` para el
 * `?redirect=` y el estado del formulario) y un `"use client"` no puede
 * exportar `metadata`.
 *
 * El `canonical` es lo que aporta valor real aquí: sin sesión, el proxy de
 * borde manda a `/login?redirect=<ruta>` desde **cada** ruta del dashboard, y a eso
 * se suman `?error=` del callback de Google y `?mfa=required`. Son decenas de
 * URLs distintas con el mismo contenido; el canonical las colapsa en una.
 *
 * `noindex` es redundante con el default de `app/layout.tsx`, y es a propósito:
 * cuando exista el grupo público que revierta ese default, la pantalla de login
 * no debe depender de que alguien se acuerde de excluirla.
 */
export const metadata: Metadata = {
  title: "Iniciar sesión",
  description: "Accede a tu cuenta de TenderFlow para consultar licitaciones, pipeline y análisis competitivo.",
  robots: { index: false, follow: false },
  alternates: { canonical: "/login" },
};

/**
 * Monta los providers y el `Toaster`, que antes vivían en el layout raíz.
 *
 * El motivo original de tenerlos arriba sigue vigente y por eso se replican
 * aquí: un `toast()` disparado en /login se descartaba en silencio cuando el
 * Toaster sólo existía en `(dashboard)`. Lo que cambió es el alcance — el
 * layout raíz los servía también a la superficie pública, que no los usa.
 *
 * `/login` conserva la CSP estricta con nonce (`src/proxy.ts` la excluye del
 * conjunto prerenderizado a propósito: es la superficie de credenciales), así
 * que leer `headers()` aquí es correcto y necesario para el script de tema.
 */
export default async function LoginLayout({ children }: { children: React.ReactNode }) {
  const nonce = (await headers()).get("x-nonce") ?? undefined;

  return (
    <Providers nonce={nonce}>
      <RouteProgress />
      {children}
      <Toaster />
      <LiveRegion />
    </Providers>
  );
}
