"use client";

import Link from "next/link";
import { useState, type ComponentProps } from "react";

/**
 * Enlace que solo se precarga cuando el visitante muestra intención: puntero
 * encima, foco de teclado o el primer toque en una pantalla táctil.
 *
 * Las fichas de los hubs son ISR desde que su ruta declara
 * `generateStaticParams`, y Next precarga **entera** —datos incluidos— una
 * ruta estática en cuanto su `<Link>` entra en el viewport
 * (`node_modules/next/dist/docs/01-app/02-guides/prefetching.md`). Con
 * cincuenta fichas por página, una sola visita en frío disparaba hasta
 * cincuenta generaciones ISR y otras tantas llamadas a la API, que corre en un
 * único proceso. Mientras las fichas fueron dinámicas eso no pasaba: una ruta
 * dinámica sin `loading.js` no se precarga. Así se vuelve a ese coste sin
 * perder la navegación inmediata hacia la ficha que de verdad se va a abrir:
 * la intención llega unos cientos de milisegundos antes que el clic, y eso es
 * lo que tarda la precarga cuando la ficha ya está en la caché del edge.
 *
 * Es el patrón que la propia documentación propone para listas largas
 * (`HoverPrefetchLink`), con el foco y el toque añadidos para que el teclado y
 * el móvil no se queden fuera.
 */
export function EnlacePrecargaIntencion({
  onMouseEnter,
  onFocus,
  onTouchStart,
  ...props
}: Omit<ComponentProps<typeof Link>, "prefetch">) {
  const [intencion, setIntencion] = useState(false);

  return (
    <Link
      {...props}
      // `null` es el comportamiento por defecto de Next; `false`, ninguna precarga.
      prefetch={intencion ? null : false}
      onMouseEnter={(evento) => {
        setIntencion(true);
        onMouseEnter?.(evento);
      }}
      onFocus={(evento) => {
        setIntencion(true);
        onFocus?.(evento);
      }}
      onTouchStart={(evento) => {
        setIntencion(true);
        onTouchStart?.(evento);
      }}
    />
  );
}
