"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import {
  LazyMotion,
  domAnimation,
  m,
  animate,
  useMotionValue,
  useReducedMotion,
  type HTMLMotionProps,
} from "motion/react";

/**
 * App-wide motion provider. Uses LazyMotion + the `m` component so only the
 * `domAnimation` feature bundle ships, keeping the JS payload small. `strict`
 * forbids the heavyweight `motion.*` components — always use `m.*`.
 */
export function MotionProvider({ children }: { children: React.ReactNode }) {
  return (
    <LazyMotion features={domAnimation} strict>
      {children}
    </LazyMotion>
  );
}

/* ── Entrance / stagger ────────────────────────────────────────────── */

export function FadeIn({
  children,
  delay = 0,
  y = 8,
  className,
  ...props
}: HTMLMotionProps<"div"> & { delay?: number; y?: number }) {
  const reduce = useReducedMotion();
  return (
    <m.div
      className={className}
      initial={reduce ? false : { opacity: 0, y }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] as const, delay }}
      {...props}
    >
      {children}
    </m.div>
  );
}

/** Container that staggers the entrance of its direct `Stagger.Item` children. */
export function Stagger({
  children,
  className,
  stagger = 0.06,
  ...props
}: HTMLMotionProps<"div"> & { stagger?: number }) {
  const reduce = useReducedMotion();
  return (
    <m.div
      className={className}
      initial={reduce ? false : "hidden"}
      animate="show"
      variants={{
        hidden: {},
        show: { transition: { staggerChildren: reduce ? 0 : stagger } },
      }}
      {...props}
    >
      {children}
    </m.div>
  );
}

const itemVariants = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] as const } },
};

function StaggerItem({ children, className, ...props }: HTMLMotionProps<"div">) {
  return (
    <m.div className={className} variants={itemVariants} {...props}>
      {children}
    </m.div>
  );
}
Stagger.Item = StaggerItem;

/* ── Page transition ───────────────────────────────────────────────── */

/** Subtle fade/slide when the route changes. No-op under reduced motion. */
export function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const reduce = useReducedMotion();
  if (reduce) return <>{children}</>;
  return (
    <m.div
      key={pathname}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] as const }}
    >
      {children}
    </m.div>
  );
}

/* ── Animated number ───────────────────────────────────────────────── */

interface ParsedNumber {
  prefix: string;
  suffix: string;
  value: number;
  decimals: number;
}

/** Extract the first numeric token from a formatted (es-ES) string. */
function parseFormatted(input: string): ParsedNumber | null {
  const match = input.match(/-?[\d.,]*\d/);
  if (!match) return null;
  const raw = match[0];
  const start = match.index ?? 0;
  const prefix = input.slice(0, start);
  const suffix = input.slice(start + raw.length);

  const hasComma = raw.includes(",");
  const decimals = hasComma ? raw.length - raw.lastIndexOf(",") - 1 : 0;
  const normalized = raw.replace(/\./g, "").replace(",", ".");
  const value = Number.parseFloat(normalized);
  if (Number.isNaN(value)) return null;
  return { prefix, suffix, value, decimals };
}

export interface AnimatedNumberProps {
  /** Pre-formatted display string (es-ES). Falls back to static if unparsable. */
  value: string;
  className?: string;
  durationMs?: number;
}

/**
 * Counts up to the numeric portion of a formatted string while preserving its
 * prefix/suffix and decimal precision. Respects `prefers-reduced-motion`.
 */
export function AnimatedNumber({ value, className, durationMs = 800 }: AnimatedNumberProps) {
  const reduce = useReducedMotion();
  const parsed = React.useMemo(() => parseFormatted(value), [value]);
  const mv = useMotionValue(parsed?.value ?? 0);
  const [animated, setAnimated] = React.useState(value);
  const prev = React.useRef(parsed?.value ?? 0);

  React.useEffect(() => {
    if (!parsed || reduce) {
      prev.current = parsed?.value ?? prev.current;
      return;
    }
    const formatter = new Intl.NumberFormat("es-ES", {
      minimumFractionDigits: parsed.decimals,
      maximumFractionDigits: parsed.decimals,
    });
    mv.set(prev.current);
    const controls = animate(mv, parsed.value, {
      duration: durationMs / 1000,
      ease: [0.22, 1, 0.36, 1] as const,
      onUpdate: (n) => setAnimated(`${parsed.prefix}${formatter.format(n)}${parsed.suffix}`),
    });
    prev.current = parsed.value;
    return () => controls.stop();
  }, [parsed, reduce, mv, durationMs]);

  const shown = parsed && !reduce ? animated : value;

  return (
    <span className={className} aria-label={value}>
      {shown}
    </span>
  );
}
