import { cn } from "@/lib/utils";

/** TF Ligatura monogram — stroke version, adapts via currentColor */
function TFMark({ size = 24, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={2.7}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* T crossbar + F top bar on shared axis */}
      <path d="M3.5 6 H20.5" />
      {/* T stem */}
      <path d="M12 6 V19" />
      {/* F middle arm */}
      <path d="M12 12 H18.5" />
    </svg>
  );
}

interface TenderFlowLogoProps {
  /** Show/hide the wordmark next to the icon */
  showText?: boolean;
  /** Size of the icon box in px */
  boxSize?: number;
  className?: string;
}

export function TenderFlowLogo({
  showText = true,
  boxSize = 32,
  className,
}: TenderFlowLogoProps) {
  const iconSize = Math.round(boxSize * 0.58);
  const radius = Math.round(boxSize * 0.26);

  return (
    <span className={cn("flex items-center gap-2", className)}>
      {/* Green app-icon box */}
      <span
        style={{
          width: boxSize,
          height: boxSize,
          borderRadius: radius,
          flexShrink: 0,
        }}
        className="grid place-items-center bg-primary text-primary-foreground shadow-[0_8px_18px_-10px_hsl(var(--primary)/0.7)]"
      >
        <TFMark size={iconSize} />
      </span>

      {showText && (
        <span className="min-w-0 leading-tight">
          <span className="block truncate text-[15px] font-bold tracking-normal">
            TenderFlow
          </span>
          <span className="block truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Sector público
          </span>
        </span>
      )}
    </span>
  );
}

/** Compact icon-only version for collapsed sidebar */
export function TenderFlowIcon({ size = 32 }: { size?: number }) {
  return <TenderFlowLogo showText={false} boxSize={size} />;
}
