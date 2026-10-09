"use client";

/**
 * Webhooks — integración de alertas con los sistemas del cliente.
 *
 * El backend llevaba tiempo completo (firma HMAC, reintentos con backoff,
 * DNS-pinning, historial de entregas) y no había forma de usarlo sin llamar a
 * la API a mano. Esta pantalla es esa superficie.
 *
 * **Dos vistas desde el mismo módulo (S4.2).** Un webhook ya no es un recurso
 * de instancia: pertenece a una organización y lo gestiona cualquier miembro
 * con permiso de escritura.
 *
 * - `WebhooksEquipoView` es la de `/equipo`: los webhooks de TU organización,
 *   con alta, edición y ping. Es la que usa el 99% de la gente.
 * - `WebhooksGlobales` (una sección de Ops › Administración) es la vista
 *   **global** del administrador de la instancia: todas las filas, incluidas
 *   las que no tienen dueño (las anteriores a la revisión `v108`), en modo
 *   lectura de estado. Se conserva porque esas integraciones sin organización
 *   siguen entregando y alguien tiene que poder verlas. Fue una pestaña propia
 *   de Ops hasta 2026-10; en producción no tenía ni una fila.
 *
 * Las piezas viven en `webhooks/` y las dos consultas en
 * `_hooks/use-webhooks-ambito.ts`: aquí solo queda quién ve qué y con qué
 * permiso, que es la única decisión que las dos vistas no comparten.
 */

import * as React from "react";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import { useWebhooksDeEquipo, useWebhooksGlobales } from "../_hooks/use-webhooks-ambito";
import { CreateForm } from "./webhooks/create-form";
import { Listado } from "./webhooks/listado";
import { SecretNotice } from "./webhooks/secret-notice";

/**
 * Webhooks del equipo. Es lo que se monta en `/equipo` para `owner`/`admin`.
 *
 * Vive en este módulo y no en `equipo/` porque la maquinaria (alta con secret,
 * ping, historial de entregas) es exactamente la misma que la vista global y
 * duplicarla habría dejado dos pantallas que se desincronizan.
 */
export function WebhooksEquipoView() {
  const organizationId = useActiveOrganizationId();
  const { data, isPending, error, refetch } = useWebhooksDeEquipo(organizationId);
  const [newSecret, setNewSecret] = React.useState<string | null>(null);

  return (
    <div className="mx-auto w-full max-w-4xl space-y-4">
      {newSecret && <SecretNotice secret={newSecret} onDismiss={() => setNewSecret(null)} />}

      {/* El formulario conserva su contrato de dos estados: crear sin ámbito
          es un caso válido suyo, y «todavía no se sabe» no lo es. */}
      <CreateForm organizationId={organizationId ?? null} onCreated={setNewSecret} />

      <Listado
        webhooks={data}
        isPending={isPending}
        error={error}
        onRetry={() => void refetch()}
        editable
        vacio="Crea uno para recibir en Slack, en Teams o en tus propios sistemas lo que pasa en las oportunidades de tu equipo."
      />
    </div>
  );
}

/**
 * Sección de Ops › Administración: todos los webhooks de la instancia, en lectura.
 *
 * No permite crear ni editar a propósito. Crear un webhook exige decir a qué
 * organización pertenece, y esa decisión se toma dentro del equipo (en
 * `/equipo`), no desde una consola que ve todas las organizaciones a la vez.
 * Lo que esta sección sí resuelve es lo que ninguna otra puede: ver las
 * integraciones **sin dueño** heredadas de antes de `v108` y el estado de
 * entrega de todo el conjunto.
 *
 * Sin guarda propia: la pone `administracion-view.tsx`, que es quien la monta.
 */
export function WebhooksGlobales() {
  const { data, isPending, error, refetch } = useWebhooksGlobales();

  return (
    <section id="webhooks" aria-labelledby="ops-webhooks" className="space-y-3">
      <div>
        <h2 id="ops-webhooks" className="text-tf-body font-semibold">
          Webhooks
        </h2>
        <p className="mt-1 max-w-prose text-muted-foreground text-tf-meta">
          Todos los de la instancia, en solo lectura. Cada equipo gestiona los suyos desde{" "}
          <strong className="font-medium text-foreground">Equipo › Integraciones</strong>; aquí aparecen además
          los que no tienen organización, heredados de antes de que los webhooks tuvieran dueño.
        </p>
      </div>

      <Listado
        webhooks={data}
        isPending={isPending}
        error={error}
        onRetry={() => void refetch()}
        editable={false}
        vacio="No hay ningún webhook registrado en la instancia."
      />
    </section>
  );
}
