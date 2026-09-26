"use client";

import * as React from "react";
import { Panel, SectionTitle } from "@/components/console/panel";
import { PursuitActivity, type ActorConocido } from "@/components/pursuits/pursuit-activity";
import { usePursuitKit } from "@/hooks/use-pursuit-kit";
import type { Pursuit } from "@/hooks/use-pursuits";

/**
 * El historial de la oportunidad, con los nombres que el ledger no guarda.
 *
 * `pursuit_events` se persistía desde v61 y no lo pintaba ninguna pantalla: en
 * un espacio compartido nadie veía quién había movido qué. Los actores son ids
 * (los nombres, de los miembros de la organización) y los marcados del kit
 * guardan la clave del documento, no su nombre: el nombre sale del kit, que la
 * ficha ya tiene en caché (`PrecargaFicha`), así que no añade petición.
 */
export function HistorialFicha({
  pursuit,
  miembros,
}: {
  pursuit: Pursuit;
  miembros: readonly ActorConocido[];
}) {
  const kit = usePursuitKit(pursuit.id);
  const kitNombres = React.useMemo(
    () => new Map((kit.data?.items ?? []).map((item) => [item.clave, item.nombre])),
    [kit.data],
  );

  return (
    <Panel>
      <SectionTitle>Historial</SectionTitle>
      <PursuitActivity events={pursuit.events} miembros={miembros} kitNombres={kitNombres} />
    </Panel>
  );
}
