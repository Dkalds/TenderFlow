import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Feature Flags",
};

export default function FeatureFlagsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
