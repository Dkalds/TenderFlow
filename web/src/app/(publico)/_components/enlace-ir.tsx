import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * «Ir a» de la superficie pública: texto en primario con `ArrowRight` detrás,
 * y al pasar el ratón solo cambia el color. Es la misma forma que `EnlaceIr` de
 * la consola, escrita aparte porque aquel vive en un módulo cliente que una
 * ruta pública no puede importar sin cargar su grafo (ver `piel-publica.ts`).
 *
 * `ArrowRight` y no `ArrowUpRight`: la flecha diagonal dice «sales de
 * TenderFlow», y estos enlaces llevan a otra página del propio sitio.
 */
export function EnlaceIrPublico({
  href,
  children,
  className,
}: {
  href: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "text-primary hover:text-foreground focus-visible:ring-ring inline-flex w-fit items-center gap-1.5 rounded-sm text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none",
        className,
      )}
    >
      {children}
      <ArrowRight className="h-3.5 w-3.5 flex-none" aria-hidden="true" />
    </Link>
  );
}
