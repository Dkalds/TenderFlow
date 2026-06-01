import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Active Learning",
};

export default function ActiveLearningLayout({ children }: { children: React.ReactNode }) {
  return children;
}
