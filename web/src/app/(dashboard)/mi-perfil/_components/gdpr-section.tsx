"use client";

/**
 * RGPD — exportar / eliminar mis datos (F13·C3.3b, plan Pliegos+RAG).
 *
 * Derecho de portabilidad y al olvido: la exportación baja un ZIP y el borrado
 * es irreversible, de ahí la confirmación en dos pasos y el cierre de sesión.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { Panel, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { apiMutate, fetchBlobWithAuth } from "@/lib/api-client";

export function GdprSection() {
  const [confirmDelete, setConfirmDelete] = useState(false);

  const exportMut = useMutation({
    // El endpoint devuelve un ZIP: `fetchBlobWithAuth` es la variante de
    // `fetchWithAuth` que no parsea el cuerpo pero conserva la redirección a
    // /login en 401 y el `ApiError` con el `detail` RFC-7807.
    mutationFn: () => fetchBlobWithAuth("/api/v1/me/data"),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `mis-datos-${new Date().toISOString().slice(0, 10)}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("Descarga iniciada.");
    },
    onError: () => toast.error("No se pudieron exportar tus datos."),
  });

  const deleteMut = useMutation({
    // `DELETE /me` exige el cuerpo `{"confirmation": "DELETE"}`
    // (`DeleteMyDataRequest`, `api/routes/me.py`), como en Ajustes › Datos y
    // cuenta: sin él la API responde 422 y no se borra nada.
    mutationFn: () => apiMutate("DELETE", "/api/v1/me", { confirmation: "DELETE" }),
    onSuccess: () => {
      toast.success("Datos eliminados. Cerrando sesión…");
      setTimeout(() => {
        window.location.href = "/login";
      }, 1500);
    },
    onError: () => {
      toast.error("No se pudieron eliminar los datos.");
      setConfirmDelete(false);
    },
  });

  function handleDeleteClick() {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    deleteMut.mutate();
  }

  return (
    <Panel>
      <PanelTitle title="Mis datos (RGPD)" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Exporta una copia de todos tus datos o elimínalos para siempre (derechos de portabilidad y de supresión,
        artículos 15 y 17 del RGPD). Incluye tu Watchlist, reglas de seguimiento, perfil, notificaciones, claves
        de API y valoraciones.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" variant="outline" onClick={() => exportMut.mutate()} disabled={exportMut.isPending}>
          <Download aria-hidden="true" />
          {exportMut.isPending ? "Exportando…" : "Exportar mis datos"}
        </Button>
        <Button
          size="sm"
          variant={confirmDelete ? "destructive" : "outline"}
          onClick={handleDeleteClick}
          disabled={deleteMut.isPending}
          className={confirmDelete ? undefined : "text-destructive hover:bg-destructive/10"}
        >
          {deleteMut.isPending
            ? "Eliminando…"
            : confirmDelete
              ? "¿Confirmar eliminación?"
              : "Eliminar mis datos"}
        </Button>
        {confirmDelete && !deleteMut.isPending && (
          <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
            Cancelar
          </Button>
        )}
      </div>
    </Panel>
  );
}
