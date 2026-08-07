"use client";

/**
 * Mi cuenta — derechos GDPR ejercitables sin escribir una petición a mano.
 *
 * `GET /me/data` (export completo en ZIP) y `DELETE /me` (anonimización y
 * borrado) existían desde hacía tiempo sin ninguna superficie: ejercer un
 * derecho reconocido por ley exigía usar curl. Esta pantalla es esa superficie.
 *
 * El borrado pide escribir el email literal, no un "¿estás seguro?": es
 * irreversible y anonimiza todo el histórico del usuario, así que la
 * confirmación tiene que costar más que un clic accidental.
 */

import * as React from "react";
import { Download, ShieldAlert, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { SpaceShell } from "@/components/layout/space-shell";
import { useSession } from "@/lib/auth";

function ExportCard() {
  const [downloading, setDownloading] = React.useState(false);

  const download = async () => {
    setDownloading(true);
    try {
      // El endpoint devuelve un ZIP, no JSON: se descarga como blob en vez de
      // pasar por `fetchWithAuth`, que parsea la respuesta.
      const response = await fetch("/api/v1/me/data", { credentials: "include" });
      if (!response.ok) throw new Error(String(response.status));
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "tenderflow-mis-datos.zip";
      link.click();
      URL.revokeObjectURL(url);
      toast.success("Export descargado");
    } catch {
      toast.error("No se pudo generar el export");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">Exportar mis datos</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-muted-foreground mb-3 text-xs">
          Descarga un ZIP con todo lo que la aplicación guarda asociado a tu cuenta: perfil, watchlist, vistas
          guardadas, reglas de alerta y registro de auditoría.
        </p>
        <Button onClick={() => void download()} disabled={downloading} variant="outline">
          <Download className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          {downloading ? "Preparando…" : "Descargar mis datos"}
        </Button>
      </CardContent>
    </Card>
  );
}

function DeleteAccountCard({ email }: { email: string }) {
  const [confirmation, setConfirmation] = React.useState("");
  const [deleting, setDeleting] = React.useState(false);
  const matches = confirmation.trim().toLowerCase() === email.toLowerCase();

  const remove = async () => {
    setDeleting(true);
    try {
      const response = await fetch("/api/v1/me", {
        method: "DELETE",
        credentials: "include",
      });
      if (!response.ok) throw new Error(String(response.status));
      toast.success("Cuenta eliminada");
      window.location.href = "/login";
    } catch {
      toast.error("No se pudo eliminar la cuenta");
      setDeleting(false);
    }
  };

  return (
    <Card className="border-destructive/40">
      <CardHeader className="pb-3">
        <CardTitle className="text-destructive flex items-center gap-2 text-sm">
          <ShieldAlert className="h-4 w-4" aria-hidden="true" />
          Eliminar mi cuenta
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-muted-foreground mb-3 text-xs">
          Anonimiza tu histórico y revoca todas tus API keys y sesiones.{" "}
          <strong className="text-foreground">No se puede deshacer.</strong> Si querés conservar una copia, exportá tus
          datos antes.
        </p>
        <label htmlFor="confirm-email" className="mb-1.5 block text-xs font-medium">
          Escribí <span className="font-mono">{email}</span> para confirmar
        </label>
        <Input
          id="confirm-email"
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
          placeholder={email}
          autoComplete="off"
          className="max-w-sm"
        />
        <Button variant="destructive" className="mt-3" disabled={!matches || deleting} onClick={() => void remove()}>
          <Trash2 className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          {deleting ? "Eliminando…" : "Eliminar mi cuenta definitivamente"}
        </Button>
      </CardContent>
    </Card>
  );
}

export default function MiCuentaPage() {
  const { user, isLoading } = useSession();

  if (isLoading) return <Skeleton className="m-4 h-40 w-full max-w-2xl" />;

  return (
    <SpaceShell spaceKey="mi-cuenta">
      <div className="mx-auto w-full max-w-2xl space-y-4 p-4">
        <ExportCard />
        {user?.email && <DeleteAccountCard email={user.email} />}
      </div>
    </SpaceShell>
  );
}
