/**
 * El índice HHI sobre una regla de tres zonas: competitivo, moderado y
 * concentrado.
 *
 * Vivía dentro de `competidores-cifras.tsx`; ahora la usan también las filas
 * de «Concentración por segmento», y las dos leen los umbrales del mismo sitio
 * (`_hooks/mercado-segmentos.ts`). Decorativa (`aria-hidden`): la cifra y su
 * zona van escritas al lado.
 */

import { HHI_CONCENTRADO, HHI_MODERADO } from "../_hooks/mercado-segmentos";

/** Tope de la regla: por encima el marcador se queda en el extremo. */
const HHI_TOPE = 4000;

export function ReglaHhi({ hhi, compacta = false }: { hhi: number; compacta?: boolean }) {
  const escala = (valor: number) => (Math.min(valor, HHI_TOPE) / HHI_TOPE) * 100;
  const moderado = escala(HHI_MODERADO);
  const concentrado = escala(HHI_CONCENTRADO);
  return (
    <div aria-hidden="true">
      <svg className={compacta ? "h-2 w-full" : "h-3 w-full"} viewBox="0 0 100 12" preserveAspectRatio="none">
        <rect y="3" width={moderado - 0.6} height="6" fill="hsl(var(--primary))" fillOpacity="0.18" />
        <rect x={moderado} y="3" width={concentrado - moderado - 0.6} height="6" fill="hsl(var(--primary))" fillOpacity="0.32" />
        <rect x={concentrado} y="3" width={100 - concentrado} height="6" fill="hsl(var(--primary))" fillOpacity="0.5" />
        <rect x={Math.max(0, escala(hhi) - 0.75)} y="0" width="1.5" height="12" fill="hsl(var(--foreground))" />
      </svg>
      {!compacta && (
        <div className="mt-0.5 flex text-tf-micro text-muted-foreground">
          <span className="basis-[37.5%]">competitivo</span>
          <span className="basis-1/4">moderado</span>
          <span className="basis-[37.5%]">concentrado</span>
        </div>
      )}
    </div>
  );
}
