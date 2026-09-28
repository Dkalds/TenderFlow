import { SpaceShellEsqueleto } from "@/components/layout/space-shell-esqueleto";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Esqueleto de ruta con la forma real de la pantalla: el marco del espacio
 * (la misma cabecera de `SpaceShell`, con `bleed`), la columna del maestro y la
 * ficha al lado.
 *
 * Dibujaba un título y cuatro tarjetas de KPI, que era la silueta de la
 * pantalla anterior. Un esqueleto que promete una forma y entrega otra hace
 * saltar el layout justo cuando llega el dato, que es lo contrario de para lo
 * que está.
 */
export default function EmpresasLoading() {
  return (
    <SpaceShellEsqueleto spaceKey="empresas" bleed>
      <div className="flex h-full min-h-0">
        <div className="border-border/60 flex w-[560px] flex-none flex-col gap-2 border-r p-4">
          <Skeleton className="mb-1 h-8 w-full rounded-md" />
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-full rounded-md" />
          ))}
        </div>
        <div className="bg-card flex min-w-0 flex-1 flex-col gap-3 p-5">
          {[72, 64, 120, 140].map((height) => (
            <Skeleton key={height} className="w-full rounded-xl" style={{ height }} />
          ))}
        </div>
      </div>
    </SpaceShellEsqueleto>
  );
}
