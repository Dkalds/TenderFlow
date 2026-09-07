"use client";

/**
 * Editores de fila del perfil de capacidad (S2.2).
 *
 * Viven aparte de `organizacion-capacidad-card.tsx` porque son cuatro formas
 * distintas —certificación, ejercicio facturado, referencia y perfil de
 * equipo— y juntarlas con el estado y el guardado pasaba de las 300 líneas
 * que permite `max-lines` (cuya allowlist solo puede encoger).
 */

import * as React from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Schemas } from "@/lib/api-types";

export type Certificacion = Schemas["OrganizationCertification"];
export type Facturacion = Schemas["OrganizationFacturacion"];
export type Referencia = Schemas["OrganizationReferencia"];
export type PerfilEquipo = Schemas["OrganizationTeamProfile"];

function Campo({
  etiqueta,
  ancho = "min-w-40 flex-1",
  children,
}: {
  etiqueta: string;
  ancho?: string;
  children: React.ReactNode;
}) {
  return (
    <label className={`${ancho} space-y-1.5 text-sm font-medium`}>
      {etiqueta}
      {children}
    </label>
  );
}

/** Marco común: título, filas, botón de añadir y borrado por fila. */
export function Seccion<T>({
  titulo,
  ayuda,
  filas,
  nueva,
  onChange,
  editable,
  render,
}: {
  titulo: string;
  ayuda: string;
  filas: T[];
  nueva: () => T;
  onChange: (filas: T[]) => void;
  editable: boolean;
  render: (fila: T, actualizar: (cambio: Partial<T>) => void) => React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <div>
        <h3 className="text-sm font-semibold">{titulo}</h3>
        <p className="text-xs text-muted-foreground">{ayuda}</p>
      </div>
      {filas.length === 0 && (
        <p className="text-sm text-muted-foreground">Sin datos declarados.</p>
      )}
      {filas.map((fila, indice) => (
        <div key={indice} className="flex flex-wrap items-end gap-2">
          {render(fila, (cambio) =>
            onChange(filas.map((actual, i) => (i === indice ? { ...actual, ...cambio } : actual))),
          )}
          {editable && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-label={`Quitar fila ${indice + 1} de ${titulo}`}
              onClick={() => onChange(filas.filter((_, i) => i !== indice))}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
        </div>
      ))}
      {editable && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => onChange([...filas, nueva()])}
        >
          <Plus className="h-4 w-4" />
          Añadir
        </Button>
      )}
    </section>
  );
}

/** Convierte lo tecleado a número; vacío es 0 y no `NaN`. */
function numero(valor: string): number {
  const parsed = Number(valor);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function filaCertificacion(
  fila: Certificacion,
  actualizar: (cambio: Partial<Certificacion>) => void,
  editable: boolean,
): React.ReactNode {
  return (
    <>
      <Campo etiqueta="Nombre" ancho="min-w-56 flex-[2]">
        <Input
          value={fila.nombre}
          disabled={!editable}
          placeholder="ISO/IEC 27001"
          onChange={(event) => actualizar({ nombre: event.target.value })}
        />
      </Campo>
      <Campo etiqueta="Ámbito" ancho="min-w-36">
        <Select
          value={fila.ambito}
          disabled={!editable}
          onValueChange={(value) => actualizar({ ambito: value as Certificacion["ambito"] })}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="company">Empresa</SelectItem>
            <SelectItem value="team">Equipo</SelectItem>
          </SelectContent>
        </Select>
      </Campo>
      <Campo etiqueta="Vigente hasta" ancho="min-w-40">
        <Input
          type="date"
          value={fila.vigente_hasta ?? ""}
          disabled={!editable}
          onChange={(event) => actualizar({ vigente_hasta: event.target.value || null })}
        />
      </Campo>
    </>
  );
}

export function filaFacturacion(
  fila: Facturacion,
  actualizar: (cambio: Partial<Facturacion>) => void,
  editable: boolean,
): React.ReactNode {
  return (
    <>
      <Campo etiqueta="Ejercicio" ancho="min-w-28">
        <Input
          type="number"
          value={fila.ejercicio}
          disabled={!editable}
          onChange={(event) => actualizar({ ejercicio: numero(event.target.value) })}
        />
      </Campo>
      <Campo etiqueta="Importe (€)" ancho="min-w-40 flex-1">
        <Input
          type="number"
          value={fila.importe_eur}
          disabled={!editable}
          onChange={(event) => actualizar({ importe_eur: numero(event.target.value) })}
        />
      </Campo>
    </>
  );
}

export function filaReferencia(
  fila: Referencia,
  actualizar: (cambio: Partial<Referencia>) => void,
  editable: boolean,
): React.ReactNode {
  return (
    <>
      <Campo etiqueta="Órgano" ancho="min-w-56 flex-[2]">
        <Input
          value={fila.organo}
          disabled={!editable}
          placeholder="Ayuntamiento de Zaragoza"
          onChange={(event) => actualizar({ organo: event.target.value })}
        />
      </Campo>
      <Campo etiqueta="Año" ancho="min-w-24">
        <Input
          type="number"
          value={fila.anio}
          disabled={!editable}
          onChange={(event) => actualizar({ anio: numero(event.target.value) })}
        />
      </Campo>
      <Campo etiqueta="Importe (€)" ancho="min-w-32">
        <Input
          type="number"
          value={fila.importe_eur ?? ""}
          disabled={!editable}
          onChange={(event) =>
            actualizar({ importe_eur: event.target.value ? numero(event.target.value) : null })
          }
        />
      </Campo>
      <Campo etiqueta="Tecnología" ancho="min-w-32">
        <Input
          value={fila.tecnologia ?? ""}
          disabled={!editable}
          placeholder="SAP"
          onChange={(event) => actualizar({ tecnologia: event.target.value || null })}
        />
      </Campo>
      <Campo etiqueta="Expediente" ancho="min-w-32">
        <Input
          value={fila.expediente_id ?? ""}
          disabled={!editable}
          placeholder="Opcional"
          onChange={(event) => actualizar({ expediente_id: event.target.value || null })}
        />
      </Campo>
    </>
  );
}

export function filaPerfil(
  fila: PerfilEquipo,
  actualizar: (cambio: Partial<PerfilEquipo>) => void,
  editable: boolean,
): React.ReactNode {
  return (
    <>
      <Campo etiqueta="Rol" ancho="min-w-56 flex-[2]">
        <Input
          value={fila.rol}
          disabled={!editable}
          placeholder="Jefe de proyecto"
          onChange={(event) => actualizar({ rol: event.target.value })}
        />
      </Campo>
      <Campo etiqueta="Años" ancho="min-w-24">
        <Input
          type="number"
          value={fila.anios}
          disabled={!editable}
          onChange={(event) => actualizar({ anios: numero(event.target.value) })}
        />
      </Campo>
      <Campo etiqueta="Personas" ancho="min-w-24">
        <Input
          type="number"
          value={fila.cantidad}
          disabled={!editable}
          onChange={(event) => actualizar({ cantidad: numero(event.target.value) })}
        />
      </Campo>
    </>
  );
}
