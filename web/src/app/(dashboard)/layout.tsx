import type { Metadata } from "next";
import { SuperficiePrivada } from "@/components/layout/superficie-privada";
import { ConnectionBanner } from "@/components/connection-banner";
import { ConsoleFrame } from "@/components/layout/console-frame";
import { CommandPalette } from "@/components/command-palette";
import { GlobalCopilot } from "@/components/copilot-panel";
import { KeyboardHelp } from "@/components/keyboard-help";
import { BandejaComparacion } from "@/components/pliego/comparacion-bandeja";
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
 * quedan los overlays propios del dashboard y la directiva de render dinámico.
 *
 * Los providers, el `Toaster`, la barra de progreso y la región viva —y la
 * lectura del nonce de la CSP que exigen— los monta `SuperficiePrivada`, la
 * misma pieza que usan `/login` y `/restablecer-contrasena`. Estaban en el
 * layout raíz, donde los heredaba también la superficie pública (una landing
 * cargando react-query y disparando un `GET /auth/me` por visita anónima), y
 * después copiados a mano en los tres layouts privados.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <SuperficiePrivada>
      <OAuthLoginTelemetry />
      {/* Dentro de `Providers`: lee el caché de React Query para saber si hay
          reintentos en vuelo (arranque en frío de la API). */}
      <ConnectionBanner />
      <ConsoleFrame>{children}</ConsoleFrame>
      <CommandPalette />
      <GlobalCopilot />
      {/* F2.8 — los expedientes marcados para comparar siguen a mano al
          cambiar de pantalla (Radar → watchlist → ficha). */}
      <BandejaComparacion />
      <KeyboardHelp />
    </SuperficiePrivada>
  );
}
