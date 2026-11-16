/**
 * Los dos derechos GDPR de Ajustes › Datos y cuenta: exportar (`GET /me/data`)
 * y borrar la cuenta (`DELETE /me`).
 *
 * Sin aviso global (`META_ERROR_EN_LINEA`): la vista dice el resultado con su
 * propio toast, de éxito y de fallo, y el global lo repetiría. Tampoco hay
 * caché que invalidar: el export no cambia nada y el borrado termina en una
 * recarga completa hacia /login.
 */
"use client";

import { useMutation } from "@tanstack/react-query";
import { apiMutate, fetchBlobWithAuth } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";

export function useExportarMisDatos() {
  return useMutation({
    // El endpoint devuelve un ZIP, no JSON: `fetchBlobWithAuth` es la
    // variante de `fetchWithAuth` que no parsea la respuesta, pero conserva
    // la redirección a /login en 401 y el `ApiError` con el `detail` RFC-7807.
    mutationFn: () => fetchBlobWithAuth("/api/v1/me/data"),
    meta: META_ERROR_EN_LINEA,
  });
}

export function useEliminarMiCuenta() {
  return useMutation({
    // Dos motivos por los que este botón devolvía 403/422 y nunca borró nada:
    //   1. `DELETE /me` cuelga de `require_recent_session` → `require_any_auth`,
    //      que rechaza toda mutación por cookie sin `X-CSRF-Token`
    //      (`api/routes/dual_auth.py`). El `fetch` crudo no lo adjuntaba;
    //      `apiMutate` sí.
    //   2. El endpoint exige cuerpo `{"confirmation": "DELETE"}`
    //      (`DeleteMyDataRequest`, `api/routes/me.py`). Se enviaba vacío.
    mutationFn: () => apiMutate("DELETE", "/api/v1/me", { confirmation: "DELETE" }),
    meta: META_ERROR_EN_LINEA,
  });
}
