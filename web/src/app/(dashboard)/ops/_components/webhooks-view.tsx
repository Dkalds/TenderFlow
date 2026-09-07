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
 * - `WebhooksView` (el default, `/ops`) es la vista **global** del
 *   administrador de la instancia: todas las filas, incluidas las que no
 *   tienen dueño (las anteriores a la revisión `v108`), en modo lectura de
 *   estado. Se conserva porque esas integraciones sin organización siguen
 *   entregando y alguien tiene que poder verlas.
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
  const { data, isPending, error } = useWebhooksDeEquipo(organizationId);
  const [newSecret, setNewSecret] = React.useState<string | null>(null);

  return (
    <div className="mx-auto w-full max-w-4xl space-y-4 p-4">
      {newSecret && <SecretNotice secret={newSecret} onDismiss={() => setNewSecret(null)} />}

      <CreateForm organizationId={organizationId} onCreated={setNewSecret} />

      <Listado
        webhooks={data}
        isPending={isPending}
        error={error}
        editable
        vacio="Creá uno para recibir en Slack, en Teams o en tus propios sistemas lo que pasa en vuestras oportunidades."
      />
    </div>
  );
}

/**
 * Vista global de `/ops`: todos los webhooks de la instancia, en lectura.
 *
 * No permite crear ni editar a propósito. Crear un webhook exige decir a qué
 * organización pertenece, y esa decisión se toma dentro del equipo (en
 * `/equipo`), no desde una consola que ve todas las organizaciones a la vez.
 * Lo que esta vista sí resuelve es lo que ninguna otra puede: ver las
 * integraciones **sin dueño** heredadas de antes de `v108` y el estado de
 * entrega de todo el conjunto.
 */
export default function WebhooksView() {
  const { data, isPending, error } = useWebhooksGlobales();

  return (
    <div className="mx-auto w-full max-w-4xl space-y-4 p-4">
      <p className="text-muted-foreground text-xs">
        Vista global de la instancia, en solo lectura. Cada equipo gestiona los suyos desde <strong>Equipo →
        Integraciones</strong>; aquí aparecen además los que no tienen organización, heredados de antes de que los
        webhooks tuvieran dueño.
      </p>

      <Listado
        webhooks={data}
        isPending={isPending}
        error={error}
        editable={false}
        vacio="No hay ningún webhook registrado en la instancia."
      />
    </div>
  );
}
