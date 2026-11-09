/**
 * `toast()` de la app, sin Sonner en el First Load.
 *
 * Sonner es un solo módulo (34,5 KB): importar `toast` arrastraba también el
 * `Toaster`, y como `toast()` se llama desde decenas de pantallas y del marco,
 * viajaba en la carga inicial de todas. Aquí `toast` tiene la misma forma de
 * llamada (`toast(...)`, `.success`, `.error`, `.info`, `.warning`, `.dismiss`)
 * pero Sonner se pide aparte: el `Toaster` diferido (`components/toaster.tsx`)
 * lo descarga en cuanto hidrata la pantalla, y una llamada que llegue antes se
 * guarda y se entrega al cargar —Sonner 2 enseña a su `Toaster` los avisos
 * creados antes de que se suscribiera—, así que ninguna se pierde.
 *
 * Lo único que cambia es que no devuelve el id del aviso: nadie lo usaba.
 * Fuera de este módulo y del `Toaster`, importar `sonner` lo prohíbe la regla
 * `no-restricted-imports` de `web/eslint.config.mjs`.
 */
import type { toast as ToastSonner } from "sonner";

type Sonner = typeof ToastSonner;
type Llamada = (sonner: Sonner) => void;

let sonner: Sonner | null = null;
let carga: Promise<void> | null = null;
let pendientes: Llamada[] = [];

/** Descarga Sonner una vez y entrega lo que esperaba. Exportada para el `Toaster` y los tests. */
export function cargarSonner(): Promise<void> {
  carga ??= import("sonner").then(
    (modulo) => {
      sonner = modulo.toast;
      const cola = pendientes;
      pendientes = [];
      for (const llamada of cola) llamada(modulo.toast);
    },
    () => {
      // Sin red: la cola se conserva y la próxima llamada lo reintenta.
      carga = null;
    },
  );
  return carga;
}

function llamar(llamada: Llamada): void {
  if (sonner) {
    llamada(sonner);
    return;
  }
  pendientes.push(llamada);
  void cargarSonner();
}

type Mensaje = Parameters<Sonner["success"]>;

export const toast = Object.assign(
  (...args: Parameters<Sonner>): void => llamar((s) => void s(...args)),
  {
    success: (...args: Mensaje): void => llamar((s) => void s.success(...args)),
    error: (...args: Mensaje): void => llamar((s) => void s.error(...args)),
    info: (...args: Mensaje): void => llamar((s) => void s.info(...args)),
    warning: (...args: Mensaje): void => llamar((s) => void s.warning(...args)),
    dismiss: (id?: number | string): void => llamar((s) => void s.dismiss(id)),
  },
);
