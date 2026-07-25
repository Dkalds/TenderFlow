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
        NProgress.start();
      }
    };

    document.addEventListener("click", handleClick);
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
