import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Feature Flags",
};

// La guarda de administrador se movió a `ops/_components/feature-flags-view.tsx`
// para que también la imponga `/ops?vista=flags`, que monta el mismo cuerpo sin
// pasar por este layout.
export default function FeatureFlagsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
