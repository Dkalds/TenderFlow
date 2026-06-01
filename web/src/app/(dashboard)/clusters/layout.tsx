import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Clusters",
};

export default function ClustersLayout({ children }: { children: React.ReactNode }) {
  return children;
}
