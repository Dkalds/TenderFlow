"use client";

import * as React from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { alQuedarOcioso } from "@/lib/al-quedar-ocioso";

/** Id del campo del nombre: el mismo en la réplica y en el formulario. */
export const CAMPO_NOMBRE_ORGANIZACION = "new-org-name";

const CrearOrganizacionForm = React.lazy(() =>
  import("./crear-organizacion-form").then((modulo) => ({ default: modulo.CrearOrganizacionForm })),
);

/**
 * El alta de organización de `/equipo`, sin react-hook-form ni zod en el First
 * Load.
 *
 * El formulario está a la vista al entrar, pero se usa poco —una organización
 * se crea una vez— y su validación (react-hook-form, el resolver y el esquema
 * de zod: ~100 KB sin comprimir, medido el 2026-10-25) era lo más pesado de la
 * pantalla. Aquí se pinta primero una réplica inerte con el mismo marcado —el
 * mismo HTML en servidor y en el primer render, sin salto— y el formulario de
 * verdad se descarga cuando el navegador queda ocioso o en cuanto alguien
 * apunta al formulario, lo que llegue antes. Lo escrito en la réplica y el foco
 * pasan al formulario al sustituirla.
 *
 * La réplica no envía: con el campo vacío su botón está apagado como el del
 * formulario, y con texto el intento solo adelanta la carga.
 */
export function CrearOrganizacion() {
  const [activo, setActivo] = React.useState(false);
  const [nombre, setNombre] = React.useState("");
  const [enfocado, setEnfocado] = React.useState(false);
  // En una transición: mientras llega el módulo, React deja la réplica en
  // pantalla en vez de cambiarla por el `fallback`, que la remontaría.
  const activar = React.useCallback(() => React.startTransition(() => setActivo(true)), []);
  React.useEffect(() => alQuedarOcioso(activar), [activar]);

  const replica = (
    <FormularioInerte nombre={nombre} onNombre={setNombre} onEnfocado={setEnfocado} onIntencion={activar} />
  );
  return (
    <React.Suspense fallback={replica}>
      {activo ? <CrearOrganizacionForm nombreInicial={nombre} enfocar={enfocado} /> : replica}
    </React.Suspense>
  );
}

/** El mismo marcado que `CrearOrganizacionForm`, sin validación ni envío. */
function FormularioInerte({
  nombre,
  onNombre,
  onEnfocado,
  onIntencion,
}: {
  nombre: string;
  onNombre: (nombre: string) => void;
  onEnfocado: (enfocado: boolean) => void;
  onIntencion: () => void;
}) {
  return (
    <form
      noValidate
      className="flex flex-wrap items-end gap-2"
      onPointerEnter={onIntencion}
      onSubmit={(event) => {
        event.preventDefault();
        onIntencion();
      }}
    >
      <Field label="Nombre de la organización" htmlFor={CAMPO_NOMBRE_ORGANIZACION} className="min-w-56 flex-1">
        <Input
          id={CAMPO_NOMBRE_ORGANIZACION}
          placeholder="p. ej. Equipo comercial"
          value={nombre}
          onFocus={() => {
            onEnfocado(true);
            onIntencion();
          }}
          onBlur={() => onEnfocado(false)}
          onChange={(event) => onNombre(event.target.value)}
        />
      </Field>
      <Button type="submit" disabled={!nombre.trim()}>
        <Plus aria-hidden="true" />
        Crear organización
      </Button>
    </form>
  );
}
