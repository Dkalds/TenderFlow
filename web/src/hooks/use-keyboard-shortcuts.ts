"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export function useKeyboardShortcuts() {
  const router = useRouter();

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Ctrl+K / Cmd+K focuses search from anywhere (even inputs)
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        document.querySelector<HTMLInputElement>("[data-search-input]")?.focus();
        return;
      }

      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement
      )
        return;

      switch (e.key) {
        case "/":
          e.preventDefault();
          document.querySelector<HTMLInputElement>("[data-search-input]")?.focus();
          break;
        case "1":
          router.push("/resumen");
          break;
        case "2":
          router.push("/detalle");
          break;
        case "3":
          router.push("/competidores");
          break;
        case "4":
          router.push("/investigador");
          break;
        case "5":
          router.push("/pipeline-alertas");
          break;
        case "Escape":
          document.querySelector<HTMLButtonElement>("[data-close-panel]")?.click();
          break;
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [router]);
}
