"use client";

import { Suspense, useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import NProgress from "nprogress";

// Constant motion (a progress bar filling) wants `linear`, not NProgress's
// default `ease` (review-animations / emil-design-eng easing decision tree:
// hover/color changes get `ease`, constant motion gets `linear`).
NProgress.configure({ showSpinner: false, trickleSpeed: 200, easing: "linear" });

function RouteProgressInner() {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    NProgress.done();
  }, [pathname, searchParams]);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      const target = (e.target as HTMLElement).closest("a");
      if (
        target &&
        target.href &&
        target.target !== "_blank" &&
        !target.hasAttribute("download") &&
        target.origin === window.location.origin &&
        target.pathname !== window.location.pathname
      ) {
        // NProgress.start() inserta un nodo en <body> y fuerza un recálculo de
        // layout síncrono. En páginas con árboles DOM grandes (tablas, charts)
        // ese reflow corre dentro del propio handler de click y puede bloquear
        // el hilo principal el tiempo suficiente para disparar warnings de INP.
        // Lo difiere un frame para que no cuente como tiempo de procesamiento
        // del input.
        requestAnimationFrame(() => NProgress.start());
      }
    };

    document.addEventListener("click", handleClick, { passive: true });
    return () => document.removeEventListener("click", handleClick);
  }, []);

  return null;
}

export function RouteProgress() {
  return (
    <Suspense fallback={null}>
      <RouteProgressInner />
    </Suspense>
  );
}
