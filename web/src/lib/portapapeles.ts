import { toast } from "sonner";

/**
 * Copia un texto y lo confirma con un aviso breve. Si el navegador lo niega
 * (contexto no seguro, permiso retirado), lo dice: el valor sigue a la vista
 * para copiarlo a mano, y callar dejaría creer que ya está en el portapapeles.
 */
export async function copiarAlPortapapeles(texto: string, confirmacion: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(texto);
    toast.success(confirmacion);
  } catch {
    toast.error("No se pudo copiar. Selecciónalo y cópialo a mano.");
  }
}
