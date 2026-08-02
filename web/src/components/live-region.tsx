"use client";

import * as React from "react";
import { create } from "zustand";

interface AnnouncerState {
  /** Mensaje vigente; `key` se incrementa para repetir un texto idéntico. */
  message: { text: string; key: number };
  announce: (text: string) => void;
}

const useAnnouncerStore = create<AnnouncerState>((set) => ({
  message: { text: "", key: 0 },
  announce: (text) => set((s) => ({ message: { text, key: s.message.key + 1 } })),
}));

/**
 * Anuncia un cambio a los lectores de pantalla.
 *
 * La app tenía **un solo `aria-live`** (en /login), así que cambiar un filtro,
 * pasar de skeleton a datos o ver el recuento saltar de 4.000 a 12 era
 * silencioso — en un producto cuya interacción central es filtrar y leer el
 * recuento. Este hook centraliza el canal para no repartir regiones `live`
 * sueltas por el árbol, que compiten entre sí y se pisan.
 */
export function useAnnounce() {
  return useAnnouncerStore((s) => s.announce);
}

/**
 * Anuncia `text` cada vez que cambia, saltándose el primer render.
 *
 * El montaje inicial no es un cambio: anunciarlo duplicaría lo que el lector ya
 * está leyendo al entrar en la página.
 */
export function useAnnounceOnChange(text: string | null | undefined) {
  const announce = useAnnounce();
  const previous = React.useRef<string | null | undefined>(undefined);

  React.useEffect(() => {
    if (previous.current !== undefined && previous.current !== text && text) {
      announce(text);
    }
    previous.current = text;
  }, [text, announce]);
}

/**
 * Región `aria-live` única, montada una vez en el layout raíz.
 *
 * `polite` porque ninguno de estos mensajes es una emergencia: interrumpir al
 * usuario a mitad de frase por un recuento de filas es peor que esperar.
 */
export function LiveRegion() {
  const message = useAnnouncerStore((s) => s.message);

  return (
    <div aria-live="polite" aria-atomic="true" className="sr-only">
      {/* La `key` fuerza un nodo nuevo: repetir el mismo texto no dispararía el
          anuncio si React reutilizase el nodo de texto existente. */}
      <span key={message.key}>{message.text}</span>
    </div>
  );
}
