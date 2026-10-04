import Link from "next/link";
import { TenderFlowLogo } from "@/components/layout/tenderflow-logo";
import { cn } from "@/lib/utils";
import { KICKER } from "./piel-publica";

/**
 * Carcasa de la puerta: `/login`, `/restablecer-contrasena` y el 404 raíz.
 *
 * Las tres se ven sin sesión y son el paso entre la portada y la consola, así
 * que hablan el idioma de la portada (decisión D4, 2026-09-26): cabecera
 * mínima con el logo enlazado a `/`, y debajo una composición editorial
 * alineada a la izquierda —rótulo, titular en Fraunces y una línea de
 * entrada— con el formulario, si lo hay, en un panel sólido a la derecha.
 *
 * Lo que se fue: el login tenía una red de partículas animada en canvas, una
 * retícula con máscara radial, un halo y una tarjeta de cristal con `shadow-xl`
 * centrada, el bloque de login por defecto de las plantillas. La portada había
 * retirado ese ornamento el 2026-09-03 y la puerta se quedó con él; restablecer
 * contraseña, que es el mismo recorrido, tenía además otra composición. Ahora
 * las tres comparten esta.
 *
 * De todo eso volvió una cosa, y solo a `/login`: la red de partículas, por
 * decisión del dueño (2026-10-04), en la ranura `fondo`
 * (`login/_components/fondo-particulas.tsx`). La retícula, el halo, el cristal
 * y la sombra siguen fuera, y el panel sigue siendo sólido: tapa la red.
 *
 * Una sola animación de entrada del contenido, la del panel (200 ms): es una
 * pantalla que se ve una vez por sesión. El orden de tabulación es el visual
 * —logo, lo que cuelgue del texto (`children`), el panel y, si hay fondo, su
 * botón de pausa al pie—, a cualquier ancho: en móvil las columnas se apilan en
 * ese mismo orden.
 *
 * Sin `"use client"`: la monta tanto el 404 raíz (servidor) como el login
 * (cliente). `main#main-content` con `tabIndex={-1}` es el destino del enlace
 * de salto del layout raíz, como en el resto de la aplicación.
 */
export function Puerta({
  kicker = "Acceso",
  titulo,
  lede,
  children,
  panel,
  fondo,
}: {
  kicker?: string;
  titulo: string;
  /** Una línea bajo el titular. */
  lede?: React.ReactNode;
  /** Lo que cuelga del texto: enlaces de salida, destinos. */
  children?: React.ReactNode;
  /** El formulario. Sin él la composición es de una columna. */
  panel?: React.ReactNode;
  /**
   * Capa decorativa que se pinta detrás de todo. Va al final del DOM, para no
   * adelantarse en el orden de tabulación, y queda detrás por su `-z-10`
   * dentro del contexto que abre `isolate`.
   */
  fondo?: React.ReactNode;
}) {
  return (
    <div className="bg-background relative isolate flex min-h-screen flex-col">
      <header className="border-border/60 border-b">
        <div className="mx-auto flex w-full max-w-6xl items-center px-6 py-3.5">
          <Link
            href="/"
            aria-label="TenderFlow — inicio"
            className="focus-visible:ring-ring rounded-sm focus-visible:ring-2 focus-visible:outline-none"
          >
            <TenderFlowLogo boxSize={30} />
          </Link>
        </div>
      </header>

      <main
        id="main-content"
        tabIndex={-1}
        className={cn(
          "mx-auto grid w-full max-w-6xl flex-1 content-start items-start gap-x-14 gap-y-10 px-6 pt-10 pb-16 md:pt-16",
          panel != null && "lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]",
        )}
      >
        <div className="max-w-[46ch]">
          <p className={KICKER}>{kicker}</p>
          <h1 className="font-display text-tf-hero mt-4 text-balance">{titulo}</h1>
          {lede != null && <p className="text-tf-lede text-muted-foreground mt-4 font-normal">{lede}</p>}
          {children ? <div className="mt-8">{children}</div> : null}
        </div>

        {panel != null && (
          <div className="border-border/70 bg-card animate-in fade-in-0 slide-in-from-bottom-2 anim-duration-200 rounded-xl border p-6">
            {panel}
          </div>
        )}
      </main>

      {fondo}
    </div>
  );
}
