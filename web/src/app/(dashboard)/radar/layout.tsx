import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Radar",
};

export default function RadarLayout({ children }: { children: React.ReactNode }) {
  return children;
}
