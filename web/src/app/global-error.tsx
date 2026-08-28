"use client";

import { useEffect } from "react";
import { reportError } from "@/lib/report-error";

/**
 * Último recinto de contención: un fallo en el layout raíz o en `Providers`
 * ocurre por encima de `(dashboard)/error.tsx`, así que hasta ahora caía en la
 * pantalla por defecto de Next — en inglés, sin marca y sin salida.
 *
 * `global-error` reemplaza el documento entero, incluidos `<html>` y `<body>`:
 * no puede apoyarse en los providers ni en los componentes de UI (el fallo
 * puede venir precisamente de ahí), así que va con estilos en línea y sin
 * dependencias.
 *
 * La única excepción a esa regla es `report-error`, y va razonada: aquí llegan
 * los errores más graves de la aplicación —los que dejan la pantalla en
 * blanco— y hasta ahora esta página los pintaba y los olvidaba, sin avisar a
 * nadie. El módulo se importa a sabiendas de la restricción: no tiene
 * dependencias, no toca el DOM y está escrito para no lanzar nunca, así que no
 * puede ser él quien tumbe la pantalla de emergencia. El `digest` que se le
 * enseña al usuario es el mismo que viaja en el reporte, de modo que un
 * "Código: 1a2b3c" en un correo de soporte se cruza con la línea del log sin
 * tener que preguntar nada más.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    reportError("global-error", error, undefined, "global-error");
  }, [error]);

  return (
    <html lang="es">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "1.5rem",
          background: "#090E11",
          color: "#F2EFEC",
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
        }}
      >
        <main style={{ maxWidth: "32rem", textAlign: "center" }}>
          <p
            style={{
              margin: 0,
              fontSize: "0.6875rem",
              fontWeight: 600,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "#F0834B",
            }}
          >
            TenderFlow
          </p>
          <h1 style={{ margin: "0.75rem 0 0", fontSize: "1.5rem", lineHeight: 1.25 }}>
            La aplicación no ha podido arrancar
          </h1>
          <p style={{ margin: "0.75rem 0 0", fontSize: "0.875rem", color: "#9AA5AB" }}>
            El error ocurrió antes de que cargara la interfaz. Reintentá; si vuelve a pasar, recargá
            la página o avisá al equipo con el código de abajo.
          </p>
          {error.digest && (
            <p
              style={{
                margin: "1rem 0 0",
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                fontSize: "0.75rem",
                color: "#9AA5AB",
              }}
            >
              Código: {error.digest}
            </p>
          )}
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: "1.5rem",
              padding: "0.5rem 1.25rem",
              borderRadius: "0.625rem",
              border: "none",
              background: "#F0834B",
              color: "#0B1418",
              fontSize: "0.875rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Reintentar
          </button>
        </main>
      </body>
    </html>
  );
}
