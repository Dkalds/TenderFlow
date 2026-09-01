import type { Metadata } from "next";
import { headers } from "next/headers";
import { Providers } from "@/components/providers";
import { RouteProgress } from "@/components/route-progress";
import { Toaster } from "@/components/toaster";
import { LiveRegion } from "@/components/live-region";
import { ConnectionBanner } from "@/components/connection-banner";
import { ConsoleFrame } from "@/components/layout/console-frame";
import { CommandPalette } from "@/components/command-palette";
import { GlobalCopilot } from "@/components/copilot-panel";
import { KeyboardHelp } from "@/components/keyboard-help";
import { OAuthLoginTelemetry } from "@/components/oauth-login-telemetry";

export const dynamic = "force-dynamic";

/**
 * Nada del dashboard se indexa. Hoy es redundante con el default de
 * `app/layout.tsx`, pero declararlo aquí hace que la privacidad del producto no
 * dependa de un default heredado que la superficie pública tendrá que revertir.
 */
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

/**
 * Layout del dashboard. El marco vive en `ConsoleFrame` (cliente: necesita la
 * ruta activa para decidir entre superficie de consola y cromo heredado); aquí
 * quedan los providers, los overlays globales y la directiva de render
 * dinámico.
 *
 * Los providers estaban en el layout raíz, donde los heredaba también la
 * superficie pública: una landing de marketing cargando react-query, el
 * `SessionProvider` (con su `GET /auth/me` por visita anónima) y el CSS de
 * Leaflet. Viven aquí y en `login/layout.tsx`, que son las dos superficies que
 * los usan de verdad.
 *
 * El nonce se lee aquí por el mismo motivo: sacarlo del layout raíz devolvió el
 * prerender a la superficie pública. Esta ruta ya era `force-dynamic`, así que
 * leer `headers()` no cuesta nada.
 */
export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const nonce = (await headers()).get("x-nonce") ?? undefined;

  return (
    <Providers nonce={nonce}>
      <OAuthLoginTelemetry />
      <RouteProgress />
      {/* Dentro de `Providers`: lee el caché de React Query para saber si hay
          reintentos en vuelo (arranque en frío de la API). */}
      <ConnectionBanner />
      <ConsoleFrame>{children}</ConsoleFrame>
      <CommandPalette />
      <GlobalCopilot />
      <KeyboardHelp />
      <Toaster />
      <LiveRegion />
    </Providers>
  );
}
