"use client";

import * as React from "react";
import { Aviso } from "@/components/console/aviso";
import { Button } from "@/components/ui/button";
import { volverAEntrar } from "@/lib/reautenticacion";

/**
 * Lo que se enseña en lugar del error cuando una acción sensible pide volver a
 * entrar (`pideReautenticacion`). Sin la cifra del margen: es configuración de
 * la API y no se copia aquí.
 */
export function AvisoReautenticacion({
  accion,
  irA,
}: {
  /** Lo que la persona intentaba, en infinitivo: «borrar la organización». */
  accion: string;
  /** Solo para los tests; por defecto, navegación completa al login. */
  irA?: (destino: string) => void;
}) {
  const [saliendo, setSaliendo] = React.useState(false);
  return (
    <Aviso
      tone="warning"
      role="alert"
      title={`Vuelve a entrar para ${accion}`}
      action={
        <Button
          size="sm"
          variant="outline"
          disabled={saliendo}
          onClick={() => {
            setSaliendo(true);
            void volverAEntrar(irA);
          }}
        >
          Volver a entrar
        </Button>
      }
    >
      Por seguridad, este cambio solo se acepta poco después de iniciar sesión. Al volver estarás en esta misma
      pantalla para repetirlo.
    </Aviso>
  );
}
