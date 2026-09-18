/**
 * Error por campo y su enlace accesible (S7.2).
 *
 * El contrato es uno solo para los seis formularios: el mensaje vive en un
 * `<p>` con id propio justo debajo del control, y el control lo nombra en su
 * `aria-describedby` y se marca `aria-invalid`. Así el lector de pantalla lee
 * el error al llegar al campo, que es donde hace falta, y no solo en un aviso
 * general que ya pasó.
 *
 * Sin error no se pinta nada ni se añade ningún atributo: el formulario se ve
 * exactamente igual que antes de tener esquema.
 */

/** Une ids de `aria-describedby`, descartando los vacíos. */
export function describedBy(...ids: Array<string | false | null | undefined>): string | undefined {
  const limpios = ids.filter((id): id is string => typeof id === "string" && id !== "");
  return limpios.length > 0 ? limpios.join(" ") : undefined;
}

/** Id del mensaje de error de un control con id `campoId`. */
export function idError(campoId: string): string {
  return `${campoId}-error`;
}

/**
 * Atributos ARIA de un control según su error.
 *
 * `otros` son descripciones que el control ya tenía (una nota, el error
 * general del formulario) y se conservan detrás del error de campo.
 */
export function ariaCampo(
  campoId: string,
  mensaje: string | undefined,
  ...otros: Array<string | false | null | undefined>
): { "aria-invalid": true | undefined; "aria-describedby": string | undefined } {
  return {
    "aria-invalid": mensaje ? true : undefined,
    "aria-describedby": describedBy(mensaje ? idError(campoId) : null, ...otros),
  };
}

/**
 * Mensaje de error de un campo; no pinta nada si no hay error.
 *
 * `enLabel` es para los formularios cuyo `<label>` envuelve el control: ahí el
 * texto del error pasaría a formar parte del nombre accesible del campo
 * («Precio ofertado (€) Escribe un importe…»). Con `aria-hidden` el cálculo del
 * nombre lo salta, y el del `aria-describedby` lo sigue leyendo porque lo
 * referencia por id (accname 1.2, paso 2A).
 */
export function CampoError({
  campoId,
  mensaje,
  enLabel = false,
}: {
  campoId: string;
  mensaje: string | undefined;
  enLabel?: boolean;
}) {
  if (!mensaje) return null;
  return (
    <span
      id={idError(campoId)}
      aria-hidden={enLabel || undefined}
      className="text-destructive block text-xs font-normal"
    >
      {mensaje}
    </span>
  );
}
