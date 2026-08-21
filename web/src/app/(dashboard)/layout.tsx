import type { Metadata } from "next";
import { ConsoleFrame } from "@/components/layout/console-frame";
import { CommandPalette } from "@/components/command-palette";
import { GlobalCopilot } from "@/components/copilot-panel";
import { KeyboardHelp } from "@/components/keyboard-help";

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
 * quedan los overlays globales y la directiva de render dinámico.
 */
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <ConsoleFrame>{children}</ConsoleFrame>
      <CommandPalette />
      <GlobalCopilot />
      <KeyboardHelp />
    </>
  );
}
