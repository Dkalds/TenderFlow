"use client";

/**
 * Claves de API — crearlas, rotarlas y revocarlas desde el producto, con su
 * tier (C2.3, D25; CU-14).
 *
 * `/me/keys` listaba y rotaba, pero **no creaba**: para tener una clave había
 * que ejecutar un script del repositorio. Y `api_key_tiers` existía desde `v28`
 * con su columna en `api_keys` sin que ninguna ruta ni middleware la leyera, así
 * que el límite de una clave se descubría por un 429. Después, la pantalla
 * creaba y listaba pero no rotaba —`POST /me/keys/rotate` no tenía consumidor—
 * ni revocaba, y Ops › Administración ya decía que cada persona «crea, rota y
 * revoca las suyas».
 *
 * El secreto se enseña **una sola vez**, al crear y al rotar, en un aviso que
 * no desaparece solo (`SecretoNuevo`).
 *
 * Una clave puede nacer además con permiso para leer las alertas propias
 * (`watchlist:read`): entonces, junto al secreto, sale la URL del feed de
 * alertas para un lector de feeds (`FeedAlertas`), que lleva la clave dentro.
 */

import * as React from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { Aviso, Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { AvisoReautenticacion } from "@/components/console/aviso-reautenticacion";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useClaves, useCrearClave } from "@/hooks/use-ajustes";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import { getErrorMessage } from "@/lib/query-feedback";
import { pideReautenticacion } from "@/lib/reautenticacion";
import { ClaveFila } from "./clave-fila";
import { FeedAlertas, SCOPE_FEED_ALERTAS } from "./feed-alertas";
import { SecretoNuevo } from "./secreto-nuevo";

interface ClaveReciente {
  token: string;
  /** Al rotar, hasta cuándo vale la anterior. */
  nota?: string;
  /** Nació con `watchlist:read`: se enseña la URL del feed con ella dentro. */
  conFeed?: boolean;
}

/**
 * La clave sin marcar nace con el scope por defecto de la API (`data:read`).
 * Con el feed, se pide ese mismo y además `watchlist:read`: pedir solo el
 * segundo dejaría una clave que lee las alertas pero no el mercado.
 */
const SCOPES_CON_FEED = `data:read,${SCOPE_FEED_ALERTAS}`;

export default function ClavesView() {
  const { data, isLoading, error, refetch } = useClaves();
  const crear = useCrearClave();
  const organizationId = useActiveOrganizationId();
  const [nombre, setNombre] = React.useState("");
  const [conFeed, setConFeed] = React.useState(false);
  const [reciente, setReciente] = React.useState<ClaveReciente | null>(null);

  const claves = data?.items ?? [];

  const crearClave = () => {
    const limpio = nombre.trim();
    if (!limpio) {
      toast.error("Ponle un nombre para reconocerla después");
      return;
    }
    crear.mutate(
      conFeed ? { name: limpio, scopes: SCOPES_CON_FEED } : { name: limpio },
      {
        onSuccess: (nueva) => {
          setReciente({ token: nueva.api_key, conFeed });
          setNombre("");
          setConFeed(false);
        },
      },
    );
  };

  return (
    <div className="space-y-4">
      {reciente ? (
        <SecretoNuevo secreto={reciente.token} onCerrar={() => setReciente(null)}>
          {reciente.nota}
        </SecretoNuevo>
      ) : null}
      {reciente?.conFeed ? <FeedAlertas token={reciente.token} organizationId={organizationId ?? null} /> : null}

      <Panel>
        <PanelTitle title="Nueva clave" />
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Nombre" htmlFor="nombre-clave" className="min-w-[220px] flex-1">
            <Input
              id="nombre-clave"
              value={nombre}
              maxLength={80}
              placeholder="p. ej. Integración con nuestro CRM"
              onChange={(e) => setNombre(e.target.value)}
            />
          </Field>
          <Button size="sm" onClick={crearClave} disabled={crear.isPending}>
            <Plus aria-hidden="true" />
            Crear
          </Button>
        </div>
        <div className="mt-3 flex items-start gap-2">
          <Checkbox
            id="clave-con-feed"
            checked={conFeed}
            onCheckedChange={(valor) => setConFeed(valor === true)}
            className="mt-0.5"
          />
          <label htmlFor="clave-con-feed" className="text-tf-meta">
            Leer también mis alertas desde un lector de feeds
            <span className="block text-muted-foreground">
              Al crearla verás la URL del feed, con la clave dentro, para pegarla en Feedly, Inoreader o
              Thunderbird.
            </span>
          </label>
        </div>
        {crear.error ? (
          <div className="mt-3">
            {pideReautenticacion(crear.error) ? (
              <AvisoReautenticacion accion="crear la clave" />
            ) : (
              <Aviso tone="danger">{getErrorMessage(crear.error, "accion")}</Aviso>
            )}
          </div>
        ) : null}
      </Panel>

      <Panel>
        <PanelTitle title={`Tus claves (${claves.length})`} />
        {isLoading ? (
          <Skeleton className="h-20 w-full rounded-md" />
        ) : error ? (
          <PanelError
            variant="inline"
            title="No se pudieron cargar tus claves"
            error={error}
            onRetry={() => void refetch()}
          />
        ) : claves.length === 0 ? (
          <PanelEmpty
            size="sm"
            title="Todavía no tienes ninguna clave"
            hint="Con una clave de API, tus sistemas consultan TenderFlow sin pasar por el navegador."
          />
        ) : (
          <ul className="space-y-2">
            {claves.map((clave) => (
              <ClaveFila key={clave.id} clave={clave} onRotada={(token, nota) => setReciente({ token, nota })} />
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
