import type { Metadata } from "next";

// El título vive en el layout, como en el resto de espacios, aunque la página
// ya sea de servidor. Aquí no hay nada más: el prefetch vive en `page.tsx`
// porque un `await` en el layout dejaría la navegación en el esqueleto
// genérico del dashboard en vez de en `loading.tsx` (ver `web/AGENTS.md`, S7.1).
export const metadata: Metadata = {
  title: "Radar",
};

export default function RadarLayout({ children }: { children: React.ReactNode }) {
  return children;
}
