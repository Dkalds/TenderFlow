/**
 * Destino del enlace de activación del alta cerrada
 * (`/verificar-correo#token=…`, RFC 2026-10-21-alta-con-contrasena-tras-concesion).
 *
 * La pantalla entera vive en `_components/verificacion-correo.tsx`, que recibe
 * la navegación como prop para poder probarla: una `page.tsx` no puede exportar
 * nada más que su componente.
 */

import { VerificacionCorreo } from "./_components/verificacion-correo";

export default function VerificarCorreoPage() {
  return <VerificacionCorreo />;
}
