import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Group entrance stagger — pure CSS (emil-design-eng: "CSS animations beat
 * JS under load"; review-animations flags Framer Motion's `x`/`y`/`opacity`
 * shorthands as not hardware-accelerated). Previously built on `motion/react`
 * (`LazyMotion` + `m.div` + `staggerChildren`), which was the only reason
 * that dependency was in the bundle — removed along with it.
 *
 * `Stagger` is the container; each direct `Stagger.Item` child fades/slides
 * up (`animate-in fade-in-0 slide-in-from-bottom-2`, the same primitives
 * every other overlay in the app already uses) with a cascading delay from
 * the `tf-stagger` utility in globals.css (60ms apart, 30–80ms range per the
 * skill, capped at 6 items — stagger is decorative and must never block
 * interaction, so it also never gates on JS).
 */
export function Stagger({ children, className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("tf-stagger", className)} {...props}>
      {children}
    </div>
  );
}

function StaggerItem({ children, className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("animate-in fade-in-0 slide-in-from-bottom-2", className)} {...props}>
      {children}
    </div>
  );
}
Stagger.Item = StaggerItem;
