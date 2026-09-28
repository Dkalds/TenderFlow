"use client";

/**
 * Datos y cuenta — derechos GDPR ejercitables sin escribir una petición a mano.
 *
 * `GET /me/data` (export completo en ZIP) y `DELETE /me` (anonimización y
 * borrado) existían desde hacía tiempo sin ninguna superficie: ejercer un
 * derecho reconocido por ley exigía usar curl. Esta pantalla es esa superficie.
 *
 * El borrado pide escribir el email literal, no un "¿estás seguro?": es
 * irreversible y anonimiza todo el histórico del usuario, así que la
 * confirmación tiene que costar más que un clic accidental.
 *
 * Vista compartida por `/mi-cuenta` (ruta heredada) y por `?vista=cuenta` del
 * espacio Ajustes (C7.5). El cuerpo vive aquí y no en el `page.tsx` de la ruta
 * por el mismo motivo que las seis vistas de Ops: un `page.tsx` importado por
 * otro módulo es a la vez boundary de ruta y componente, y Next no puede
 * tratarlo como lo primero.
 */

import * as React from "react";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { Panel, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { apiMutate, fetchBlobWithAuth } from "@/lib/api-client";
import { useSession } from "@/lib/auth";

function ExportCard() {
  const [downloading, setDownloading] = React.useState(false);

  const download = async () => {
    setDownloading(true);
    try {
      // El endpoint devuelve un ZIP, no JSON: `fetchBlobWithAuth` es la
      // variante de `fetchWithAuth` que no parsea la respuesta, pero conserva
      // la redirección a /login en 401 y el `ApiError` con el `detail` RFC-7807.
      const blob = await fetchBlobWithAuth("/api/v1/me/data");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "tenderflow-mis-datos.zip";
      link.click();
      URL.revokeObjectURL(url);
      toast.success("Datos descargados");
    } catch {
      toast.error("No se pudieron preparar tus datos");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Panel>
      <PanelTitle title="Exportar mis datos" />
      <p className="text-muted-foreground mb-3 text-tf-meta">
        Descarga un ZIP con todo lo que TenderFlow guarda de tu cuenta: perfil, Watchlist, vistas guardadas, reglas
        de alerta y registro de actividad.
      </p>
      <Button size="sm" onClick={() => void download()} disabled={downloading} variant="outline">
        <Download aria-hidden="true" />
        {downloading ? "Preparando…" : "Descargar mis datos"}
      </Button>
    </Panel>
  );
}

function DeleteAccountCard({ email }: { email: string }) {
  const [confirmation, setConfirmation] = React.useState("");
  const [deleting, setDeleting] = React.useState(false);
  const matches = confirmation.trim().toLowerCase() === email.toLowerCase();

  const remove = async () => {
    setDeleting(true);
    try {
      // Dos motivos por los que este botón devolvía 403/422 y nunca borró nada:
      //   1. `DELETE /me` cuelga de `require_recent_session` → `require_any_auth`,
      //      que rechaza toda mutación por cookie sin `X-CSRF-Token`
      //      (`api/routes/dual_auth.py`). El `fetch` crudo no lo adjuntaba;
      //      `apiMutate` sí.
      //   2. El endpoint exige cuerpo `{"confirmation": "DELETE"}`
      //      (`DeleteMyDataRequest`, `api/routes/me.py`). Se enviaba vacío.
      await apiMutate("DELETE", "/api/v1/me", { confirmation: "DELETE" });
      toast.success("Cuenta eliminada");
      window.location.href = "/login";
    } catch {
      toast.error("No se pudo eliminar la cuenta");
      setDeleting(false);
    }
  };

  return (
    <Panel tono="danger">
      <PanelTitle title="Eliminar mi cuenta" />
      <p className="text-muted-foreground mb-3 text-tf-meta">
        Anonimiza tu histórico y revoca todas tus claves de API y sesiones.{" "}
        <strong className="text-foreground">No se puede deshacer.</strong> Si quieres conservar una copia, exporta tus
        datos antes.
      </p>
      <Field
        htmlFor="confirm-email"
        label={
          <>
            Escribe <span className="font-mono">{email}</span> para confirmar
          </>
        }
      >
        <Input
          id="confirm-email"
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
          placeholder={email}
          autoComplete="off"
          className="max-w-sm"
        />
      </Field>
      <Button
        size="sm"
        variant="destructive"
        className="mt-3"
        disabled={!matches || deleting}
        onClick={() => void remove()}
      >
        {deleting ? "Eliminando…" : "Eliminar mi cuenta definitivamente"}
      </Button>
    </Panel>
  );
}

export default function CuentaView() {
  const { user, isLoading } = useSession();

  if (isLoading) return <Skeleton className="h-40 w-full max-w-2xl rounded-xl" />;

  return (
    <div className="mx-auto w-full max-w-2xl space-y-4">
      <ExportCard />
      {user?.email && <DeleteAccountCard email={user.email} />}
    </div>
  );
}
