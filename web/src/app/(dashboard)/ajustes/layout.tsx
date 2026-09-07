import type { Metadata } from "next";

// El título vive en un layout de servidor porque la página del espacio es
// cliente (necesita `?vista=`) y no puede exportar `metadata`.
export const metadata: Metadata = {
  title: "Ajustes",
};

export default function AjustesLayout({ children }: { children: React.ReactNode }) {
  return children;
}
