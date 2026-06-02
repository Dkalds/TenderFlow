import type { Metadata } from "next";
import { AdminGuard } from "@/components/admin-guard";

export const metadata: Metadata = {
  title: "Administracion",
};

export default function AdministracionLayout({ children }: { children: React.ReactNode }) {
  return <AdminGuard>{children}</AdminGuard>;
}
