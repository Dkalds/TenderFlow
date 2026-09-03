import type { Metadata } from "next";
import Link from "next/link";
import { ThemeProvider } from "next-themes";
import { TenderFlowLogo } from "@/components/layout/tenderflow-logo";
import { CONTACT_EMAIL, solicitarAccesoHref } from "@/lib/contacto";
import { CONTENIDO } from "./_content/landing";
import { EnlaceSolicitarAcceso } from "./_components/enlace-solicitar-acceso";

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
 * cliente que exigen sesión. Todo el **contenido** que cuelga de este layout se
 * renderiza en servidor, que es lo que un rastreador puede leer; las dos islas
 * cliente que hay —`ThemeProvider` y el ancla con evento del CTA— no aportan
 * texto que dependa de la hidratación. El header es sticky con
 * la superficie `tf-glass` de la casa (CSS puro, con fallback sólido); por eso
 * los anclajes de la landing llevan `scroll-mt-*`, o el header taparía el
 * título al que se salta.
 *
 * Los providers de la aplicación (react-query, sesión, tooltips, nuqs) no se
 * montan aquí: viven en los grupos que los usan, porque en esta superficie sólo
 * servían para engordar el bundle de una página de marketing y disparar un
 * `GET /auth/me` por visita anónima. Lo que sí monta son dos islas mínimas.
 * `EnlaceSolicitarAcceso` es la del CTA del header, y existe por lo mismo que
 * en la landing: sin su evento, el botón más persistente del sitio sería un
 * punto ciego en la medición; su ancla y su `href` llegan renderizados desde el
 * servidor, así que sin JavaScript el enlace funciona igual. El tema sí hace
 * falta: el variant `dark` del proyecto es class-driven
 * (`@custom-variant dark` en `globals.css`), así que sin la clase `.dark` un
 * visitante con el sistema en oscuro vería la landing en claro. Va **sin**
 * `nonce` a propósito — estas rutas se prerenderizan y su CSP no lo lleva
 * (ver `src/proxy.ts`).
 */
export const metadata: Metadata = {
  robots: { index: true, follow: true },
};

/* Piel de los enlaces del pie. `py-1.5` no es decorativo: sin él estos enlaces
 * miden 16 px de alto y quedan por debajo del mínimo de 24×24 px que exige
 * WCAG 2.5.8. Estaba copiada carácter a carácter en los cinco. */
const ENLACE_PIE =
  "hover:text-foreground focus-visible:ring-ring -my-1.5 inline-flex items-center rounded px-1 " +
  "py-1.5 transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none";

/* Orden deliberado: primero la superficie de datos que se puede ver sin cuenta,
 * después las tres páginas que responden a «de dónde sale esto» y sólo al final
 * lo legal. */
const ENLACES_PIE = [
  { href: "/licitaciones", texto: "Licitaciones" },
  { href: "/cpv", texto: "Por CPV" },
  { href: "/cobertura", texto: "Cobertura" },
  { href: "/metodologia", texto: "Metodología" },
  { href: "/seguridad", texto: "Seguridad" },
  { href: "/aviso-legal", texto: "Aviso legal" },
];

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
            {/* El header llevaba "Iniciar sesión" como único botón, y era el
              CTA más persistente del sitio: acompaña al visitante durante toda
              la página. Para quien llega sin cuenta —el público entero de esta
              superficie— /login no es una acción, es un muro: el alta responde
              403 y el login con Google es fail-closed sin allowlist. La propia
              FAQ lo dice ("por eso el botón principal es solicitar acceso y no
              crear una cuenta") mientras el header decía lo contrario.

              Ahora la jerarquía coincide con el producto: solicitar acceso es
              el botón, y acceder es un enlace para quien ya tiene cuenta y sabe
              lo que busca. En móvil, donde la nav de secciones está oculta,
              esto es además lo único accionable del header — razón de más para
              que no sea un callejón sin salida.

              utm_content distingue en Vercel Analytics desde qué CTA se llega a
              /login; el canonical de /login colapsa las variantes. */}
            <div className="flex items-center gap-4">
              <Link
                href="/login?utm_source=publico&utm_content=header"
                // `whitespace-nowrap`: al dejar de ser un botón con padding,
                // a 375 px "Iniciar sesión" partía en dos renglones junto a un
                // CTA de una sola línea. El texto es corto y cabe entero.
                className="text-muted-foreground hover:text-foreground focus-visible:ring-ring rounded text-sm whitespace-nowrap transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none"
              >
                Iniciar sesión
              </Link>
              <EnlaceSolicitarAcceso
                href={solicitarAccesoHref("header")}
                ubicacion="header"
                className="bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:ring-ring focus-visible:ring-offset-background inline-flex h-9 items-center justify-center rounded-md px-4 text-sm font-medium shadow transition-[transform,background-color] duration-150 ease-out focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none active:scale-[0.97]"
              >
                {CONTENIDO.ctaPrimario}
              </EnlaceSolicitarAcceso>
            </div>
          </div>
        </header>

        {/* Destino del skip link. Sin `tabIndex={-1}` el salto mueve el scroll
            pero no el foco en Safari, así que el teclado seguía atrapado en la
            cabecera después de "saltar al contenido" — mismo motivo por el que
            lo llevan los otros dos `main` de la app (/login y el dashboard). */}
        <main id="main-content" tabIndex={-1} className="flex-1">
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
              {/* Las tres páginas de evidencia —cobertura, metodología y
                seguridad— entran aquí porque hasta ahora no las enlazaba nadie:
                estaban publicadas y sólo se llegaba a ellas escribiendo la URL,
                cosa que no hace ningún visitante. Son además lo que pregunta
                quien evalúa el producto, así que el pie es el sitio donde se
                buscan. */}
              <nav
                aria-label="Enlaces del pie"
                className="text-muted-foreground flex flex-wrap items-center gap-x-5 gap-y-1 text-xs font-medium"
              >
                {ENLACES_PIE.map((enlace) => (
                  <Link key={enlace.href} href={enlace.href} className={ENLACE_PIE}>
                    {enlace.texto}
                  </Link>
                ))}
                {CONTACT_EMAIL && (
                  <a href={`mailto:${CONTACT_EMAIL}`} className={ENLACE_PIE}>
                    Contacto
                  </a>
                )}
                <Link href="/login?utm_source=publico&utm_content=footer" className={ENLACE_PIE}>
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
