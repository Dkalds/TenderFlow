"use client";

/**
 * RGPD — exportar / eliminar mis datos (F13·C3.3b, plan Pliegos+RAG).
 *
 * Derecho de portabilidad y al olvido: la exportación baja un ZIP y el borrado
 * es irreversible, de ahí la confirmación en dos pasos y el cierre de sesión.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Download, ShieldAlert, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
    onError: () => toast.error("No se pudo exportar tus datos."),
  });

  const deleteMut = useMutation({
    mutationFn: () => apiMutate("DELETE", "/api/v1/me"),
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
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldAlert className="h-5 w-5" />
          Mis datos (RGPD)
        </CardTitle>
        <CardDescription>
          Exporta una copia de todos tus datos o elimínalos permanentemente (derecho de
          portabilidad y al olvido, Art. 15/17 RGPD). Cubre tu watchlist, reglas de
          seguimiento, perfil de scoring, notificaciones, claves API y feedback.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-3">
        <Button
          variant="outline"
          onClick={() => exportMut.mutate()}
          disabled={exportMut.isPending}
          className="gap-1.5"
        >
          <Download className="h-4 w-4" />
          {exportMut.isPending ? "Exportando…" : "Exportar mis datos"}
        </Button>
        <Button
          variant={confirmDelete ? "destructive" : "outline"}
          onClick={handleDeleteClick}
          disabled={deleteMut.isPending}
          className={
            confirmDelete ? "gap-1.5" : "gap-1.5 text-destructive hover:bg-destructive/10"
          }
        >
          <Trash2 className="h-4 w-4" />
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
      </CardContent>
    </Card>
  );
}
