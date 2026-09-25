"use client";

import * as React from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

/** Heurística de id_externo (misma que usaba el linkifier plano previo). */
const EXPEDIENTE_RE = /\b[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+(?:-[A-Z0-9]+)*\b/g;

/**
 * Reescribe tokens tipo id_externo como links Markdown a /detalle?lic=…,
 * saltando los segmentos que ya son links `[…](…)` o código `` `…` ``.
 */
export function linkifyExpedientes(text: string): string {
  const segments = text.split(/(`[^`]*`|\[[^\]]*\]\([^)]*\))/g);
  return segments
    .map((seg, i) => (i % 2 === 1 ? seg : seg.replace(EXPEDIENTE_RE, (m) => `[${m}](/detalle?lic=${m})`)))
    .join("");
}

// A nivel de módulo, no dentro del render: son las mismas en cada respuesta, y
// recrearlas en cada token era una asignación más por turno y por frame.
const REMARK_PLUGINS = [remarkGfm];

const COMPONENTES: Components = {
  a: ({ children, href }) => (
    <a href={href} className="text-primary underline hover:no-underline">
      {children}
    </a>
  ),
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  h1: ({ children }) => <h3 className="mt-3 mb-2 text-sm font-semibold">{children}</h3>,
  h2: ({ children }) => <h3 className="mt-3 mb-2 text-sm font-semibold">{children}</h3>,
  h3: ({ children }) => <h4 className="mt-2 mb-1 text-sm font-medium">{children}</h4>,
  ul: ({ children }) => <ul className="mb-2 list-disc space-y-0.5 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal space-y-0.5 pl-5">{children}</ol>,
  code: ({ children }) => <code className="bg-muted rounded px-1 py-0.5 font-mono text-xs">{children}</code>,
  table: ({ children }) => (
    <div className="mb-2 overflow-x-auto">
      <table className="w-full border-collapse text-xs">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="border-border bg-muted border px-2 py-1 text-left font-medium">{children}</th>,
  td: ({ children }) => <td className="border-border border px-2 py-1">{children}</td>,
};

interface MarkdownAnswerProps {
  text: string;
  className?: string;
}

/**
 * Renderer Markdown de respuestas del LLM (copiloto, investigador, resumen).
 * Sustituye a los renderAnswer de texto plano: soporta las tablas y headings
 * que pide el prompt, y conserva los IDs de expediente como links a /detalle.
 *
 * `memo`: parsear Markdown es lo más caro del hilo, y mientras una respuesta
 * se emite el hilo entero se repinta en cada frame. Con `memo` solo se vuelve
 * a parsear el turno cuyo texto cambió; los anteriores se quedan como estaban.
 */
export const MarkdownAnswer = React.memo(function MarkdownAnswer({ text, className }: MarkdownAnswerProps) {
  return (
    <div className={cn("text-sm leading-relaxed", className)}>
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={COMPONENTES}>
        {linkifyExpedientes(text)}
      </ReactMarkdown>
    </div>
  );
});
