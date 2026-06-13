import type { Metadata } from "next";
import { AdminGuard } from "@/components/admin-guard";

export const metadata: Metadata = {
  title: "Active Learning",
};

export default function ActiveLearningLayout({ children }: { children: React.ReactNode }) {
  return <AdminGuard>{children}</AdminGuard>;
}
