import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Cuentas",
};

export default function CuentasLayout({ children }: { children: React.ReactNode }) {
  return children;
}
