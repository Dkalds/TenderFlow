import type { Metadata } from "next";
import Link from "next/link";
import { TenderFlowLogo } from "@/components/layout/tenderflow-logo";

/**
 * Layout de la superficie pública.
 *
 * Su única responsabilidad de SEO es **revertir el `noindex` heredado**:
 * `app/layout.tsx` marca toda la aplicación como no indexable porque
 * TenderFlow nació siendo un dashboard privado entero, y ese sigue siendo el
 * default correcto. Lo que se indexa es la excepción, y la excepción se declara
 * aquí, en el grupo de rutas que de verdad es público.
 *
 * No monta `ConsoleFrame` ni la paleta de comandos ni el copiloto: son piezas
 * cliente que exigen sesión. Todo lo que cuelga de este layout es HTML de
 * servidor, que es lo que un rastreador puede leer.
 */
export const metadata: Metadata = {
  robots: { index: true, follow: true },
};

export default function PublicoLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="border-b border-border/60">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-4">
          <Link href="/" aria-label="TenderFlow — inicio">
            <TenderFlowLogo boxSize={30} />
          </Link>
          <Link
            href="/login"
            className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground shadow transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            Iniciar sesión
          </Link>
        </div>
      </header>

      <main id="main-content" className="flex-1">
        {children}
      </main>

      <footer className="border-t border-border/60">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-8 text-xs text-muted-foreground">
          <span>TenderFlow — Inteligencia de licitaciones del sector público español</span>
          {/* `py-1.5` no es decorativo: sin él el enlace mide 16 px de alto y
              queda por debajo del mínimo de 24×24 px que exige WCAG 2.5.8. */}
          <Link
            href="/login"
            className="-my-1.5 inline-flex items-center rounded px-1 py-1.5 font-medium hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Acceder
          </Link>
        </div>
      </footer>
    </div>
  );
}
