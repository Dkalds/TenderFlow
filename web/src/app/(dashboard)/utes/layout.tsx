import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "UTEs",
};

export default function UtesLayout({ children }: { children: React.ReactNode }) {
  return children;
}
