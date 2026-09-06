"use client";

/**
 * Salida a Grafana.
 *
 * La URL viene de `runtime-config` y no de una constante: es entorno, y ADR-014
 * §3 prohíbe hardcodearla. Sin configurar, la tarjeta explica qué variable
 * falta en vez de ofrecer un enlace roto.
 */

import { ExternalLink } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { getGrafanaUrl } from "@/lib/runtime-config";

export function GrafanaCard() {
  const grafanaUrl = getGrafanaUrl();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ExternalLink className="h-5 w-5" />
          Métricas Prometheus / Grafana
        </CardTitle>
        <CardDescription>Métricas detalladas disponibles en Grafana</CardDescription>
      </CardHeader>
      <CardContent>
        {grafanaUrl ? (
          <Button asChild>
            <a href={grafanaUrl} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="mr-2 h-4 w-4" />
              Abrir Grafana
            </a>
          </Button>
        ) : (
          <p className="text-sm text-muted-foreground">
            URL de Grafana no configurada. Define{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              NEXT_PUBLIC_GRAFANA_URL
            </code>{" "}
            en el entorno del frontend para habilitar el enlace.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
