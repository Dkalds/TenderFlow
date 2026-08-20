"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Scroll edge effect — el separador del cromo flotante sólo existe cuando hay
 * contenido debajo (apple-design §12).
 *
 * La barra de ámbito y la barra móvil son superficies translúcidas apoyadas
 * sobre el contenedor con scroll. Con un `border-b` fijo el resultado era una
 * línea dura permanente: en el tope de la página separa dos superficies del
 * mismo color y anuncia una profundidad que no existe. Aquí el separador es un
 * gradiente que se desvanece y **sólo aparece cuando el contenido se ha
 * desplazado por debajo**, así que deja de ser decoración y pasa a decir algo:
 * hay contenido oculto arriba.
 *
 * La detección es un `IntersectionObserver` sobre un centinela de 1px colocado
 * al principio del contenedor con scroll — ni un listener de `scroll` ni
 * trabajo por frame. El estado viaja por contexto porque quien scrollea
 * (`#main-content`, en `dashboard-shell.tsx`) y quien pinta el borde
 * (`scope-bar.tsx` y la barra móvil de `console-rail.tsx`) son componentes
 * distintos del mismo marco.
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

/** `true` cuando el contenedor con scroll del marco no está en el tope. */
const ScrollEdgeStateContext = React.createContext(false);

/** Publicador: lo consume el centinela, que vive dentro del contenedor. */
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
 * Centinela: va como **primer hijo del contenedor con scroll**. Mientras se ve,
 * el contenido está en el tope y no hay borde.
 */
export function ScrollEdgeSentinel() {
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
      // El root es el contenedor con scroll, no el viewport: el marco scrollea
      // dentro de `<main>`, así que contra el viewport el centinela nunca
      // saldría de vista.
      { root: sentinel.parentElement, threshold: 0 },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      aria-hidden="true"
      data-scroll-edge-sentinel=""
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
 */
export function ScrollEdge({ active, className }: { active: boolean; className?: string }) {
  return (
    <div className="pointer-events-none relative z-30 h-0 flex-none">
      <EdgeGradient active={active} className={cn("top-0", className)} />
    </div>
  );
}

/**
 * Variante anclada **dentro** del propio cromo: sirve cuando la barra ya tiene
 * posicionamiento propio (`sticky`) y no recorta, y evita depender de cómo esté
 * colocada esa barra entre sus hermanos.
 */
export function ScrollEdgeUnder({ active, className }: { active: boolean; className?: string }) {
  return <EdgeGradient active={active} className={cn("top-full", className)} />;
}
