/**
 * Tipos de las importaciones estáticas de imágenes (`import x from "./f.webp"`).
 *
 * Normalmente los aporta `next-env.d.ts`, pero ese fichero lo genera
 * `next dev`/`next build` y está en .gitignore: en CI, `tsc --noEmit` corre
 * sobre un checkout fresco donde no existe, y cada import de imagen revienta
 * con TS2307 (pasó con los assets de la landing en el job de Frontend).
 * Referenciar aquí el mismo módulo de tipos de Next es idempotente cuando
 * `next-env.d.ts` sí está presente.
 */

/// <reference types="next/image-types/global" />
