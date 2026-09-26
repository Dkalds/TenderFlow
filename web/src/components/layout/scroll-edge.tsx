"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Scroll edge effect — el separador del cromo flotante sólo existe cuando hay
 * contenido debajo (apple-design §12).
 *
 * La barra de ámbito es una superficie translúcida apoyada sobre el contenido
 * que se desplaza. Con un `border-b` fijo el resultado era una línea dura
 * permanente: en el tope de la página separa dos superficies del mismo color y
 * anuncia una profundidad que no existe. Aquí el separador es un gradiente que
 * se desvanece y **sólo aparece cuando el contenido se ha desplazado por
 * debajo**, así que deja de ser decoración y pasa a decir algo: hay contenido
 * oculto arriba.
 *
 * La detección es un `IntersectionObserver` sobre un centinela de 1px colocado
 * donde empieza lo que se desplaza — ni un listener de `scroll` ni trabajo por
 * frame. El estado viaja por contexto porque quien scrollea y quien pinta el
 * borde son componentes distintos. Hay dos casos:
 *
 * - **El marco** (`console-frame.tsx`): se desplaza el documento. `#main-content`
 *   lleva `overflow-auto`, pero su columna tiene alto mínimo y no fijo, así que
 *   crece con el contenido y nunca desborda en vertical. El centinela va justo
 *   antes del marco y se mide contra el viewport; el borde lo pinta la barra de
 *   ámbito (`scope-bar.tsx`).
 * - **Las pantallas de alto fijo** (`SpaceShell`, Resumen): se desplaza su
 *   cuerpo, que monta su propio proveedor y abre con el centinela.
 *
 * Movimiento (docs/frontend-motion.md): se anima **sólo `opacity`**, entrada
 * 260ms con `cubic-bezier(.21,1.02,.73,1)` y salida más rápida (170ms) — el
 * sistema responde rápido, el usuario decide despacio. No lleva un
 * `motion-reduce:` propio a propósito: la regla global de `globals.css` recorta
 * las transiciones a 150ms bajo `prefers-reduced-motion: reduce` y conserva
 * justamente las de `opacity`, que aquí es la única que hay. Neutralizarla
 * entera contradiría esa política (reduced motion no es cero).
 *
 * El color sale de `--border`, el mismo token del borde que sustituye, así que
 * el gradiente sigue al tema sin usar la variante `dark:` — que en este repo no
 * está enganchada a la clase de next-themes y no seguiría al conmutador.
 */

/** `true` cuando lo que se desplaza no está en el tope. */
const ScrollEdgeStateContext = React.createContext(false);

/** Publicador: lo consume el centinela. */
const ScrollEdgePublishContext = React.createContext<((scrolled: boolean) => void) | null>(null);

export function ScrollEdgeProvider({ children }: { children: React.ReactNode }) {
  const [scrolled, setScrolled] = React.useState(false);

  // `setScrolled` es estable, así que el contexto del publicador nunca cambia
  // de identidad y el centinela no se vuelve a montar por un scroll.
  return (
    <ScrollEdgePublishContext.Provider value={setScrolled}>
      <ScrollEdgeStateContext.Provider value={scrolled}>{children}</ScrollEdgeStateContext.Provider>
    </ScrollEdgePublishContext.Provider>
  );
}

/**
 * Estado del borde para el cromo. Sin proveedor devuelve `false`: un cromo
 * montado fuera del marco no inventa un borde que no separa nada.
 */
export function useScrollEdgeState(): boolean {
  return React.useContext(ScrollEdgeStateContext);
}

/**
 * Centinela: mientras se ve, el contenido está en el tope y no hay borde.
 *
 * - `contenedor="padre"` (por defecto): va como **primer hijo del contenedor
 *   con scroll** y se mide contra él.
 * - `contenedor="documento"`: se desplaza la ventana. Va justo antes del cromo
 *   que se queda pegado arriba y se mide contra el viewport. Medido contra un
 *   padre que no desborda no saldría nunca de vista, porque el padre se
 *   desplaza entero con él: así estuvo el del marco dentro de `#main-content`,
 *   y su borde no llegó a encenderse.
 */
export function ScrollEdgeSentinel({ contenedor = "padre" }: { contenedor?: "padre" | "documento" }) {
  const publish = React.useContext(ScrollEdgePublishContext);
  const publishRef = React.useRef(publish);
  React.useEffect(() => {
    publishRef.current = publish;
  }, [publish]);

  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const sentinel = ref.current;
    // jsdom no implementa `IntersectionObserver`. Sin él el borde simplemente
    // no aparece nunca, que es el estado "en el tope": degradación segura.
    if (!sentinel || typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      (entries) => {
        const last = entries[entries.length - 1];
        if (last) publishRef.current?.(!last.isIntersecting);
      },
      // `null` es el viewport. Un cuerpo con scroll propio se mide contra sí
      // mismo: el documento no se mueve y el centinela no saldría de la ventana.
      { root: contenedor === "documento" ? null : sentinel.parentElement, threshold: 0 },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [contenedor]);

  return (
    <div
      ref={ref}
      aria-hidden="true"
      data-scroll-edge-sentinel={contenedor}
      // 1px de alto compensado con -1px de margen: necesita área real (un
      // elemento de altura 0 no intersecta en todos los motores) pero no puede
      // desplazar el contenido ni crear 1px de scroll propio.
      className="pointer-events-none -mb-px h-px"
    />
  );
}

/** El gradiente. Se posiciona en absoluto; el `top` lo fija cada variante. */
function EdgeGradient({ active, className }: { active: boolean; className?: string }) {
  return (
    <span
      aria-hidden="true"
      data-scroll-edge={active ? "on" : "off"}
      className={cn(
        "pointer-events-none absolute inset-x-0 h-3",
        "bg-[linear-gradient(to_bottom,hsl(var(--border)),transparent)]",
        "transition-opacity",
        active
          ? "opacity-100 duration-[260ms] ease-[cubic-bezier(.21,1.02,.73,1)]"
          : "opacity-0 duration-[170ms] ease-out",
        className,
      )}
    />
  );
}

/**
 * Cuelga el borde del elemento anterior sin ocupar alto: va como hermano
 * inmediato del cromo dentro de un contenedor en columna. Es la variante para
 * cromo con `overflow` propio, que recortaría un hijo absoluto.
 *
 * Sólo sirve si ese contenedor no se desplaza (la cabecera de `SpaceShell`,
 * sobre un cuerpo con scroll propio). Si el cromo es `sticky`, este hermano no
 * lo es y se va con el contenido: ahí el borde va dentro de la misma caja
 * `sticky`, con `ScrollEdgeUnder`.
 */
export function ScrollEdge({ active, className }: { active: boolean; className?: string }) {
  return (
    <div className="pointer-events-none relative z-30 h-0 flex-none">
      <EdgeGradient active={active} className={cn("top-0", className)} />
    </div>
  );
}

/**
 * `ScrollEdge` que lee su estado del proveedor más cercano. Es la forma
 * cómoda para las cabeceras de pantalla (`SpaceShell`, Resumen), que montan su
 * propio `ScrollEdgeProvider` porque ahí el que scrollea es el cuerpo de la
 * pantalla y no el documento: sin esto necesitarían un componente hijo solo
 * para poder llamar al hook dentro del proveedor.
 */
export function ScrollEdgeDelProveedor({ className }: { className?: string }) {
  return <ScrollEdge active={useScrollEdgeState()} className={className} />;
}

/**
 * Variante anclada **dentro** del propio cromo: sirve cuando la barra ya tiene
 * posicionamiento propio (`sticky`) y no recorta, y evita depender de cómo esté
 * colocada esa barra entre sus hermanos. Cuelga de la caja `sticky`, así que se
 * queda con ella mientras el documento se desplaza.
 */
export function ScrollEdgeUnder({ active, className }: { active: boolean; className?: string }) {
  return <EdgeGradient active={active} className={cn("top-full", className)} />;
}
