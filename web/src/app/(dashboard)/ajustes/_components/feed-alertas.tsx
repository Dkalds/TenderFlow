"use client";

/**
 * La URL del feed de alertas, lista para pegar en un lector de feeds.
 *
 * `GET /watchlist/feed.xml` existía pero ninguna pantalla decía su URL, y
 * además estaba roto (ver `api/routes/watchlist_feed.py`). Los lectores solo
 * guardan una URL, así que la clave va dentro, en `?token=`: se enseña junto al
 * secreto recién creado porque es el único momento en que el token está a la
 * vista. Después no se puede reconstruir, igual que la clave.
 */

import { Copy } from "lucide-react";
import * as React from "react";
import { Aviso } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { copiarAlPortapapeles } from "@/lib/portapapeles";

/** Ruta del feed; el origen se pone en el navegador (misma API que la consola). */
export const RUTA_FEED_ALERTAS = "/api/v1/watchlist/feed.xml";

/** Scope que abre el feed. Lo valida el backend; aquí solo se pide. */
export const SCOPE_FEED_ALERTAS = "watchlist:read";

export function urlFeedAlertas(origen: string, token: string, organizationId: number | null): string {
  const query = new URLSearchParams({ token });
  // Las alertas viven en la organización donde se crearon: sin ella, el feed
  // leería las de la personal.
  if (organizationId != null) query.set("organization_id", String(organizationId));
  return `${origen}${RUTA_FEED_ALERTAS}?${query.toString()}`;
}

export function FeedAlertas({ token, organizationId }: { token: string; organizationId: number | null }) {
  // Mismo patrón que la suscripción al calendario: el origen solo existe en el
  // cliente, y en el render de servidor no se inventa un host.
  const origen = React.useSyncExternalStore(
    () => () => {},
    () => window.location.origin,
    () => "",
  );
  const url = origen ? urlFeedAlertas(origen, token, organizationId) : "";

  return (
    <Aviso tone="info" title="Tus alertas en un lector de feeds">
      <p className="text-muted-foreground">
        Pega esta URL en Feedly, Inoreader, Thunderbird o el lector que uses: verás lo que casan tus alertas
        activas, igual que en Mi watchlist.
      </p>
      <div className="mt-2 flex items-center gap-1.5">
        <input
          readOnly
          aria-label="URL del feed de tus alertas"
          value={url}
          className="h-8 min-w-0 flex-1 rounded-md border border-input bg-background px-2 font-mono text-tf-micro"
          onFocus={(event) => event.currentTarget.select()}
        />
        <Button
          size="sm"
          variant="outline"
          disabled={!url}
          onClick={() => void copiarAlPortapapeles(url, "URL del feed copiada")}
        >
          <Copy aria-hidden="true" />
          Copiar
        </Button>
      </div>
      <p className="mt-1 text-tf-micro text-muted-foreground">
        La URL lleva la clave: quien la tenga lee tus alertas. Si se filtra, revoca la clave.
      </p>
    </Aviso>
  );
}
