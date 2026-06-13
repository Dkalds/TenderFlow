import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Calendario",
};

export default function CalendarioLayout({ children }: { children: React.ReactNode }) {
  return children;
}
