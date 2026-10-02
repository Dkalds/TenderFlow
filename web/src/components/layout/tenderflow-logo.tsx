import { cn } from "@/lib/utils";
import {
  MARCA_NOMBRE,
  TF_MARK_ESCALA,
  TF_MARK_PATHS,
  TF_MARK_RADIO,
  TF_MARK_STROKE,
  TF_MARK_VIEWBOX,
} from "@/lib/marca";

/**
 * Monograma TF en trazo. Toma el color de `currentColor`, así que quien lo
 * monta decide sobre qué fondo va. El trazo sale de `lib/marca.ts`, la única
 * copia que comparten el logo, el rail y las imágenes OG.
 */
function TFMark({ size = 24, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox={TF_MARK_VIEWBOX}
      aria-hidden="true"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={TF_MARK_STROKE}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {TF_MARK_PATHS.map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}

interface TenderFlowLogoProps {
  /** Muestra u oculta el wordmark junto a la marca. */
  showText?: boolean;
  /** Lado de la caja de la marca, en px. */
  boxSize?: number;
  className?: string;
}

/**
 * Marca + wordmark. La caja es plana: sin el halo de color que la rodeaba
 * (el resplandor de «app icon» de las plantillas) y sin sombra. El wordmark va
 * en `font-display` (Fraunces) a 15 px, el mínimo al que la regla de la casa
 * permite la display; la línea de sector, en sans a 11 px y en frase.
 */
export function TenderFlowLogo({ showText = true, boxSize = 32, className }: TenderFlowLogoProps) {
  const iconSize = Math.round(boxSize * TF_MARK_ESCALA);
  const radius = Math.round(boxSize * TF_MARK_RADIO);

  return (
    <span className={cn("flex items-center gap-2", className)}>
      <span
        style={{
          width: boxSize,
          height: boxSize,
          borderRadius: radius,
          flexShrink: 0,
        }}
        className="grid place-items-center bg-primary text-primary-foreground"
      >
        <TFMark size={iconSize} />
      </span>

      {showText && (
        <span className="min-w-0">
          <span className="block truncate font-display text-tf-lede font-semibold">{MARCA_NOMBRE}</span>
          <span className="block truncate text-tf-micro font-medium text-muted-foreground">Sector público</span>
        </span>
      )}
    </span>
  );
}
