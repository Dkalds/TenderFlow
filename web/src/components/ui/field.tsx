import * as React from "react";
import { cn } from "@/lib/utils";
import { describedBy, idError } from "@/lib/forms/campo";

/**
 * Un campo de formulario: etiqueta, control, pista y error, con una sola
 * jerarquía para toda la app.
 *
 * La etiqueta va a 12 px (`text-tf-meta font-medium`), **por debajo** del
 * título del panel (13 px) y no por encima: con el `Label` de shadcn a 14 px
 * copiado a mano, las pantallas de configuración tenían la etiqueta del campo
 * más grande que el título de la tarjeta que la contenía.
 *
 * Accesibilidad (contrato S7.2 de `lib/forms/campo.tsx`): la pista y el error
 * tienen id propio, y el control los nombra en `aria-describedby` y se marca
 * `aria-invalid` con error. Sin región viva por campo: el error se lee al
 * llegar al campo. Si el hijo es un único elemento, `Field` le pone esos
 * atributos (sumándolos a los que ya traiga); si el control real está más
 * dentro (el `SelectTrigger` de un `Select`), usa `ariaDeField` en él.
 */

/** Etiqueta de un campo. */
export const ETIQUETA_CAMPO = "block text-tf-meta font-medium text-foreground";
/** Pista bajo el control. */
export const AYUDA_CAMPO = "text-tf-meta text-muted-foreground";
/** Mensaje de error bajo el control. */
export const ERROR_CAMPO = "text-tf-meta text-destructive";

/** Id de la pista de un control con id `campoId`. */
export function idAyuda(campoId: string): string {
  return `${campoId}-ayuda`;
}

/**
 * Atributos ARIA del control de un `Field`: `aria-describedby` con el error (si
 * lo hay) y la pista (si la hay), y `aria-invalid` con error.
 */
export function ariaDeField(
  campoId: string,
  { hint, error }: { hint?: boolean; error?: string | null },
): { "aria-invalid": true | undefined; "aria-describedby": string | undefined } {
  return {
    "aria-invalid": error ? true : undefined,
    "aria-describedby": describedBy(error ? idError(campoId) : null, hint ? idAyuda(campoId) : null),
  };
}

export interface FieldProps {
  label: React.ReactNode;
  /** Id del control: une la etiqueta, la pista y el error. */
  htmlFor: string;
  hint?: React.ReactNode;
  /** Mensaje de error; sin él no se pinta nada ni se marca el control. */
  error?: string | null;
  className?: string;
  children: React.ReactNode;
}

type PropsAria = { "aria-describedby"?: string; "aria-invalid"?: boolean | "true" | "false" };

export function Field({ label, htmlFor, hint, error, className, children }: FieldProps) {
  const hayPista = hint != null && hint !== false && hint !== "";
  const aria = ariaDeField(htmlFor, { hint: hayPista, error });

  let control = children;
  if (React.isValidElement<PropsAria>(children)) {
    const propios = children.props;
    control = React.cloneElement(children, {
      "aria-describedby": describedBy(aria["aria-describedby"], propios["aria-describedby"]),
      "aria-invalid": aria["aria-invalid"] ?? propios["aria-invalid"],
    });
  }

  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={htmlFor} className={ETIQUETA_CAMPO}>
        {label}
      </label>
      {control}
      {hayPista && (
        <p id={idAyuda(htmlFor)} className={AYUDA_CAMPO}>
          {hint}
        </p>
      )}
      {error && (
        <p id={idError(htmlFor)} className={ERROR_CAMPO}>
          {error}
        </p>
      )}
    </div>
  );
}
