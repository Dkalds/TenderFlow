import WebhooksView from "../ops/_components/webhooks-view";

/**
 * Boundary de ruta. El cuerpo vive en `ops/_components/webhooks-view` porque
 * el espacio Ops monta la misma vista bajo `?vista=webhooks`.
 */
export default function WebhooksPage() {
  return <WebhooksView />;
}
