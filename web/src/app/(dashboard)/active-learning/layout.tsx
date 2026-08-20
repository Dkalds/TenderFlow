import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Active Learning",
};

// La guarda de administrador se movió a `ops/_components/active-learning-view.tsx`
// para que también la imponga `/ops?vista=etiquetado`, que monta el mismo cuerpo
// sin pasar por este layout.
export default function ActiveLearningLayout({ children }: { children: React.ReactNode }) {
  return children;
}
