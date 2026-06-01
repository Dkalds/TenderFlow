import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Geografia",
};

export default function GeografiaLayout({ children }: { children: React.ReactNode }) {
  return children;
}
