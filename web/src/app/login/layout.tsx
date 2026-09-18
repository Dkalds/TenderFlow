import type { Metadata } from "next";
import { SuperficiePrivada } from "@/components/layout/superficie-privada";

/**
 * Los metadatos de `/login` viven en un layout y no en la página porque
 * `login/page.tsx` es un Client Component (su `useLoginForm` lee
 * `useSearchParams` para el `?redirect=` y guarda el estado del formulario) y
 * un `"use client"` no puede exportar `metadata`.
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
 * Monta los providers y el `Toaster` vía `SuperficiePrivada`, la pieza común
 * con el dashboard y `/restablecer-contrasena`. Tenerlos aquí sigue siendo
 * necesario: un `toast()` disparado en /login se descartaba en silencio cuando
 * el Toaster sólo existía en `(dashboard)`.
 *
 * `/login` conserva la CSP estricta con nonce (`src/proxy.ts` la excluye del
 * conjunto prerenderizado a propósito: es la superficie de credenciales), y
 * `SuperficiePrivada` lee `headers()` para el script de tema.
 */
export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return <SuperficiePrivada>{children}</SuperficiePrivada>;
}
