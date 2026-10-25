import { Pencil } from "lucide-react";

/** El lápiz de la celda: solo icono, con el nombre de lo que edita. */
export function BotonEditar({ etiqueta, onClick }: { etiqueta: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={etiqueta}
      onClick={onClick}
      // 24×24 de diana (WCAG 2.5.8) con margen negativo: el rótulo no se mueve.
      className="tf-pressable text-muted-foreground hover:text-foreground hover:bg-muted -my-1 -mr-1 grid size-6 flex-none place-items-center rounded-md"
    >
      <Pencil className="h-3 w-3" aria-hidden="true" />
    </button>
  );
}
