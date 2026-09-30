"use client";

/**
 * Salida a Grafana.
 *
 * La URL viene de `runtime-config` y no de una constante: es entorno, y ADR-014
 * §3 prohíbe hardcodearla. Sin configurar, la tarjeta explica qué variable
 * falta en vez de ofrecer un enlace roto.
 */

import { ExternalLink } from "lucide-react";
import { AvisoPestanaNueva } from "@/components/ui/aviso-pestana-nueva";
import { Panel, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { getGrafanaUrl } from "@/lib/runtime-config";

export function GrafanaCard() {
  const grafanaUrl = getGrafanaUrl();

  return (
    <Panel>
      <PanelTitle title="Métricas en Grafana" hint="Las series de Prometheus, con más detalle" />
      {grafanaUrl ? (
        <Button asChild size="sm">
          <a href={grafanaUrl} target="_blank" rel="noopener noreferrer">
            Abrir Grafana
            <ExternalLink aria-hidden="true" />
            <AvisoPestanaNueva />
          </a>
        </Button>
      ) : (
        <p className="text-tf-meta text-muted-foreground">
          La URL de Grafana no está configurada. Define{" "}
          <code className="rounded-sm bg-muted px-1 py-0.5 font-mono text-tf-micro">NEXT_PUBLIC_GRAFANA_URL</code>{" "}
          en las variables de entorno de la web para activar el enlace.
        </p>
      )}
    </Panel>
  );
}
