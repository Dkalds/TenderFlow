import type { ReactNode } from "react";

/**
 * Resalta las apariciones literales de la consulta dentro de un extracto.
 *
 * Sin consulta devuelve el texto tal cual; la consulta se escapa antes de
 * entrar en el `RegExp` porque el usuario escribe lo que quiere y un `(` suelto
 * tumbaba el render.
 */
export function highlightQuery(text: string, query: string): ReactNode {
  if (!query.trim()) return text;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = text.split(new RegExp(`(${escaped})`, "gi"));
  return parts.map((part, i) =>
    part.toLowerCase() === query.toLowerCase() ? (
      <mark key={i} className="bg-yellow-200 font-semibold dark:bg-yellow-800">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}
