import type { Metadata } from "next";
import Link from "next/link";
import { ThemeProvider } from "next-themes";
import { TenderFlowLogo } from "@/components/layout/tenderflow-logo";
import { CONTACT_EMAIL } from "@/lib/contacto";

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
 * servidor, que es lo que un rastreador puede leer. El header es sticky con
 * la superficie `tf-glass` de la casa (CSS puro, con fallback sólido); por eso
 * los anclajes de la landing llevan `scroll-mt-*`, o el header taparía el
 * título al que se salta.
 *
 * El único cliente que monta es `ThemeProvider`: el resto de providers de la
 * aplicación (react-query, sesión, tooltips, nuqs) vive ahora en los grupos que
 * los usan, porque aquí sólo servían para engordar el bundle de una página de
 * marketing y disparar un `GET /auth/me` por visita anónima. El tema sí hace
 * falta: el variant `dark` del proyecto es class-driven
 * (`@custom-variant dark` en `globals.css`), así que sin la clase `.dark` un
 * visitante con el sistema en oscuro vería la landing en claro. Va **sin**
 * `nonce` a propósito — estas rutas se prerenderizan y su CSP no lo lleva
 * (ver `src/proxy.ts`).
 */
export const metadata: Metadata = {
  robots: { index: true, follow: true },
};

export default function PublicoLayout({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" disableTransitionOnChange>
      <div className="bg-background flex min-h-screen flex-col">
        <header className="tf-glass border-border/60 sticky top-0 z-40 border-b">
          <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-3.5">
            <div className="flex items-center gap-7">
              <Link
                href="/"
                aria-label="TenderFlow — inicio"
                className="focus-visible:ring-ring rounded focus-visible:ring-2 focus-visible:outline-none"
              >
                <TenderFlowLogo boxSize={30} />
              </Link>
              {/* Estos dos enlaces son la vía por la que la superficie de datos
                recibe autoridad interna. Sin ellos los hubs solo existen en el
                sitemap: rastreables, pero sin nada que los respalde. */}
              <nav aria-label="Secciones" className="hidden items-center gap-5 text-sm sm:flex">
                <Link
                  href="/licitaciones"
                  className="text-muted-foreground hover:text-foreground transition-colors duration-150"
                >
                  Licitaciones
                </Link>
                <Link
                  href="/cpv"
                  className="text-muted-foreground hover:text-foreground transition-colors duration-150"
                >
                  Por CPV
                </Link>
              </nav>
            </div>
            {/* utm_content distingue en Vercel Analytics desde qué CTA se llega
              a /login; el canonical de /login colapsa las variantes. */}
            <Link
              href="/login?utm_source=publico&utm_content=header"
              className="bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:ring-ring focus-visible:ring-offset-background inline-flex h-9 items-center justify-center rounded-md px-4 text-sm font-medium shadow transition-[transform,background-color] duration-150 ease-out focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none active:scale-[0.97]"
            >
              Iniciar sesión
            </Link>
          </div>
        </header>

        <main id="main-content" className="flex-1">
          {children}
        </main>

        <footer className="border-border/60 border-t">
          <div className="mx-auto w-full max-w-6xl px-6 py-10">
            <div className="flex flex-wrap items-start justify-between gap-6">
              <div className="max-w-[38ch]">
                <TenderFlowLogo boxSize={26} />
                <p className="text-muted-foreground mt-3 text-xs leading-relaxed">
                  Inteligencia de licitaciones públicas de tecnología enterprise en España, sobre fuentes oficiales.
                </p>
              </div>
              {/* `py-1.5` no es decorativo: sin él estos enlaces miden 16 px de
                alto y quedan por debajo del mínimo de 24×24 px que exige
                WCAG 2.5.8. */}
              <nav
                aria-label="Enlaces del pie"
                className="text-muted-foreground flex flex-wrap items-center gap-x-5 gap-y-1 text-xs font-medium"
              >
                <Link
                  href="/licitaciones"
                  className="hover:text-foreground focus-visible:ring-ring -my-1.5 inline-flex items-center rounded px-1 py-1.5 transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none"
                >
                  Licitaciones
                </Link>
                <Link
                  href="/cpv"
                  className="hover:text-foreground focus-visible:ring-ring -my-1.5 inline-flex items-center rounded px-1 py-1.5 transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none"
                >
                  Por CPV
                </Link>
                <Link
                  href="/aviso-legal"
                  className="hover:text-foreground focus-visible:ring-ring -my-1.5 inline-flex items-center rounded px-1 py-1.5 transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none"
                >
                  Aviso legal
                </Link>
                {CONTACT_EMAIL && (
                  <a
                    href={`mailto:${CONTACT_EMAIL}`}
                    className="hover:text-foreground focus-visible:ring-ring -my-1.5 inline-flex items-center rounded px-1 py-1.5 transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none"
                  >
                    Contacto
                  </a>
                )}
                <Link
                  href="/login?utm_source=publico&utm_content=footer"
                  className="hover:text-foreground focus-visible:ring-ring -my-1.5 inline-flex items-center rounded px-1 py-1.5 transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none"
                >
                  Acceder
                </Link>
              </nav>
            </div>
          </div>
        </footer>
      </div>
    </ThemeProvider>
  );
}
