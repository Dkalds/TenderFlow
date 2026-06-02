import type { Metadata } from "next";
import { AdminGuard } from "@/components/admin-guard";

export const metadata: Metadata = {
  title: "Feature Flags",
};

export default function FeatureFlagsLayout({ children }: { children: React.ReactNode }) {
  return <AdminGuard>{children}</AdminGuard>;
}
