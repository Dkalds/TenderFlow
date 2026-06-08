"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

/**
 * Decorative canvas particle field used as a page backdrop.
 *
 * Renders many small brand-colored particles that move in three distinct
 * patterns (free drift, orbit and a flow field) plus faint links between
 * nearby particles for a "data network" feel. Pure canvas, no dependencies.
 *
 * - Reads the `--primary` design token so it adapts to light/dark themes.
 * - Honors `prefers-reduced-motion` (renders a single static frame).
 * - Pauses the animation while the tab is hidden.
 * - Decorative only: `aria-hidden` + `pointer-events-none`.
 */

type Pattern = "drift" | "orbit" | "flow";

interface Particle {
  x: number;
  y: number;
  baseX: number;
  baseY: number;
  vx: number;
  vy: number;
  r: number;
  alpha: number;
  phase: number;
  speed: number;
  radius: number;
  pattern: Pattern;
}

interface ParticleFieldProps {
  className?: string;
  /** Higher = more particles. Roughly particles per ~14k px². Default 1. */
  density?: number;
  /** Draw faint links between nearby particles. Default true. */
  linked?: boolean;
}

const PATTERNS: Pattern[] = ["drift", "orbit", "flow"];

export function ParticleField({
  className,
  density = 1,
  linked = true,
}: ParticleFieldProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvasEl = canvasRef.current;
    if (!canvasEl) return;
    const ctxOrNull = canvasEl.getContext("2d", { alpha: true });
    if (!ctxOrNull) return;
    // Bind to non-nullable consts: the animation closures escape via
    // requestAnimationFrame, so TS widens captured vars back to their declared
    // (nullable) type. Explicit non-null types keep the narrowing inside them.
    const canvas: HTMLCanvasElement = canvasEl;
    const ctx: CanvasRenderingContext2D = ctxOrNull;

    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    // Brand color from the design tokens, e.g. "83 69% 36%".
    const primary =
      getComputedStyle(document.documentElement)
        .getPropertyValue("--primary")
        .trim() || "83 69% 40%";
    const stroke = (a: number) => `hsl(${primary} / ${a})`;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let width = 0;
    let height = 0;
    let particles: Particle[] = [];
    let raf = 0;
    let t = 0;

    const rand = (min: number, max: number) => min + Math.random() * (max - min);

    function spawn(): Particle {
      const x = Math.random() * width;
      const y = Math.random() * height;
      const pattern = PATTERNS[Math.floor(Math.random() * PATTERNS.length)];
      return {
        x,
        y,
        baseX: x,
        baseY: y,
        vx: rand(-0.35, 0.35),
        vy: rand(-0.35, 0.35),
        r: rand(0.6, 2.2),
        alpha: rand(0.25, 0.7),
        phase: rand(0, Math.PI * 2),
        speed: rand(0.4, 1),
        radius: rand(16, 70),
        pattern,
      };
    }

    function initParticles() {
      const area = width * height;
      const count = Math.min(
        180,
        Math.max(36, Math.round((area / 14000) * density)),
      );
      particles = Array.from({ length: count }, spawn);
    }

    function resize() {
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      initParticles();
    }

    // Cheap, smooth pseudo-noise direction field — gives organic, varied paths.
    function flowAngle(x: number, y: number, time: number) {
      return (
        (Math.sin(x * 0.0021 + time) + Math.cos(y * 0.0019 - time * 0.8)) *
        Math.PI
      );
    }

    function wrap(p: Particle) {
      if (p.x < -10) p.x = width + 10;
      else if (p.x > width + 10) p.x = -10;
      if (p.y < -10) p.y = height + 10;
      else if (p.y > height + 10) p.y = -10;
    }

    function update(p: Particle) {
      switch (p.pattern) {
        case "orbit": {
          // Orbit around a slowly drifting anchor point.
          p.baseX += p.vx * 0.25;
          p.baseY += p.vy * 0.25;
          const angle = p.phase + t * p.speed * 0.6;
          p.x = p.baseX + Math.cos(angle) * p.radius;
          p.y = p.baseY + Math.sin(angle) * p.radius;
          if (p.baseX < -80) p.baseX = width + 80;
          else if (p.baseX > width + 80) p.baseX = -80;
          if (p.baseY < -80) p.baseY = height + 80;
          else if (p.baseY > height + 80) p.baseY = -80;
          break;
        }
        case "flow": {
          const a = flowAngle(p.x, p.y, t * 0.2);
          p.x += Math.cos(a) * p.speed * 0.5;
          p.y += Math.sin(a) * p.speed * 0.5;
          wrap(p);
          break;
        }
        default: {
          // Free linear drift, wrapping around the edges.
          p.x += p.vx * p.speed;
          p.y += p.vy * p.speed;
          wrap(p);
        }
      }
    }

    function drawLinks() {
      const maxDist = 110;
      const maxDistSq = maxDist * maxDist;
      ctx.lineWidth = 1;
      for (let i = 0; i < particles.length; i++) {
        const a = particles[i];
        for (let j = i + 1; j < particles.length; j++) {
          const b = particles[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const distSq = dx * dx + dy * dy;
          if (distSq < maxDistSq) {
            const o = (1 - distSq / maxDistSq) * 0.12;
            ctx.strokeStyle = stroke(o);
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
      }
    }

    function draw() {
      ctx.clearRect(0, 0, width, height);
      if (linked) drawLinks();
      for (const p of particles) {
        ctx.fillStyle = stroke(p.alpha);
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    function tick() {
      t += 0.005;
      for (const p of particles) update(p);
      draw();
      raf = requestAnimationFrame(tick);
    }

    function start() {
      cancelAnimationFrame(raf);
      if (reduceMotion) {
        draw();
        return;
      }
      raf = requestAnimationFrame(tick);
    }

    function onVisibility() {
      if (document.hidden) cancelAnimationFrame(raf);
      else start();
    }

    resize();
    start();

    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [density, linked]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={cn("pointer-events-none absolute inset-0 h-full w-full", className)}
    />
  );
}
