import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Detalle",
};

export default function DetalleLayout({ children }: { children: React.ReactNode }) {
  return children;
}
