import { ConsoleFrame } from "@/components/layout/console-frame";
import { CommandPalette } from "@/components/command-palette";
import { GlobalCopilot } from "@/components/copilot-panel";
import { KeyboardHelp } from "@/components/keyboard-help";

export const dynamic = "force-dynamic";

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
