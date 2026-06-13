import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Observabilidad",
};

export default function ObservabilidadLayout({ children }: { children: React.ReactNode }) {
  return children;
}
