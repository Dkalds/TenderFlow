import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Resumen",
};

export default function ResumenLayout({ children }: { children: React.ReactNode }) {
  return children;
}
