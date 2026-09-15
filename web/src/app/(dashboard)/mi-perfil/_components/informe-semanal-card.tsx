"use client";

/**
 * Cuándo sale el informe semanal de la organización (T6).
 *
 * Existe por una razón concreta: el backend de T6 nace **apagado** para todas
 * las organizaciones, a propósito (ver `docs/informes-programados.md`). Sin
 * esta tarjeta el único modo de encenderlo sería un `PUT` a mano, es decir,
 * nadie lo encendería — «infraestructura sin consumidor».
 *
 * Vive junto a `TecnologiasOrganizacionCard` porque es lo mismo: un ajuste de
 * organización, no del usuario, editable sólo por owner/admin.
 *
 * La hora se guarda en **UTC** (el scheduler razona en UTC de punta a punta,
 * ADR-033) y aquí se traduce al enseñarla. La traducción se calcula sobre la
 * *próxima* entrega y no sobre una semana de referencia fija: así el horario
 * de verano sale bien en vez de con una hora de más medio año.
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useActiveOrganizationId, useOrganizations } from "@/hooks/use-organization";
import { DIAS, useGuardarReportSchedule, useReportSchedule } from "@/hooks/use-report-schedule";
import { formatDateTime, formatDiaYHora } from "@/lib/utils";

/** Tope de la lista explícita. Espejo de `ReportSchedule.destinatarios` (DTO). */
const MAX_DESTINATARIOS = 25;

const HORAS = Array.from({ length: 24 }, (_, h) => h);

/**
 * Instante UTC de la próxima entrega programada, estrictamente futura.
 *
 * Se exporta para poder probarla sin depender de la zona horaria en que corra
 * el runner: el test mira el día y la hora **UTC** del resultado.
 */
export function proximaEntrega(diaSemana: number, horaUtc: number, desde: Date = new Date()): Date {
  const cuando = new Date(desde);
  cuando.setUTCMinutes(0, 0, 0);
  cuando.setUTCHours(horaUtc);
  // `getUTCDay()` es 0 = domingo; la programación es 0 = lunes.
  const hoy = (cuando.getUTCDay() + 6) % 7;
  cuando.setUTCDate(cuando.getUTCDate() + ((diaSemana - hoy + 7) % 7));
  if (cuando.getTime() <= desde.getTime()) cuando.setUTCDate(cuando.getUTCDate() + 7);
  return cuando;
}

/**
 * Traduce `ultimo_estado` a algo que se pueda leer sin abrir los logs. Los
 * códigos los escribe `scheduler/jobs/informes_programados.py`.
 */
function explicarEstado(estado: string): string {
  if (estado.startsWith("enviado:")) {
    const [salieron, total] = estado.slice("enviado:".length).split("/");
    return salieron === total
      ? `Enviado a ${total} destinatario(s)`
      : `Enviado a ${salieron} de ${total}; el resto lo rechazó el transporte`;
  }
  if (estado === "vacio") return "No se envió: esa semana no había nada que contar";
  if (estado === "sin_destinatarios") return "No se envió: nadie con correo y el informe encendido";
  if (estado === "fallido") return "No salió ninguno: fallo del proveedor de correo";
  return estado;
}

/** Separa por líneas o comas y quita lo vacío. */
function parsearDestinatarios(texto: string): string[] {
  return texto
    .split(/[\n,;]+/)
    .map((c) => c.trim())
    .filter(Boolean);
}

export function InformeSemanalCard() {
  const activeOrganizationId = useActiveOrganizationId();
  const organizations = useOrganizations();
  const rol = organizations.data?.find((o) => o.id === activeOrganizationId)?.role;
  const puedeEditar = rol === "owner" || rol === "admin";

  // Sólo Dirección puede leer esto (el backend responde 403 al resto): se pasa
  // `null` para no gastar una petición que se sabe rechazada.
  const organizationId = puedeEditar ? activeOrganizationId : null;
  const { data, isLoading } = useReportSchedule(organizationId);
  const guardar = useGuardarReportSchedule(organizationId);

  const [activo, setActivo] = useState(false);
  const [diaSemana, setDiaSemana] = useState(0);
  const [horaUtc, setHoraUtc] = useState(7);
  const [destinatarios, setDestinatarios] = useState("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!data) return;
    /* eslint-disable react-hooks/set-state-in-effect */
    setActivo(data.activo);
    setDiaSemana(data.dia_semana);
    setHoraUtc(data.hora_utc);
    setDestinatarios((data.destinatarios ?? []).join("\n"));
    setDirty(false);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [data]);

  if (!puedeEditar) return null;

  const lista = parsearDestinatarios(destinatarios);
  const proxima = proximaEntrega(diaSemana, horaUtc);

  const enviar = () => {
    // El validador de verdad es el `EmailStr` del DTO; esto sólo existe para
    // poder decir *qué* línea está mal en vez de devolver un 422 opaco.
    const sospechosa = lista.find((c) => !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(c));
    if (sospechosa) {
      toast.error(`«${sospechosa}» no parece un correo.`);
      return;
    }
    if (lista.length > MAX_DESTINATARIOS) {
      toast.error(`Como mucho ${MAX_DESTINATARIOS} destinatarios; hay ${lista.length}.`);
      return;
    }
    guardar
      .mutateAsync({
        activo,
        dia_semana: diaSemana,
        hora_utc: horaUtc,
        destinatarios: lista.length > 0 ? lista : null,
      })
      .then(() => {
        setDirty(false);
        toast.success(
          activo
            ? `Informe programado: ${DIAS[diaSemana]} a las ${String(horaUtc).padStart(2, "0")}:00 UTC.`
            : "Informe semanal apagado.",
        );
      })
      .catch((error: unknown) =>
        toast.error(error instanceof Error ? error.message : "No se pudo guardar"),
      );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Informe semanal por correo</CardTitle>
        <CardDescription>
          El cuadro de Dirección —embudo abierto, plazos a catorce días, ganadas y perdidas de la
          semana— entregado por correo, con el mismo contenido en un PDF adjunto. Nace apagado.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Cargando programación…</p>
        ) : (
          <>
            <label className="flex items-center gap-3 text-sm">
              <Switch
                checked={activo}
                onCheckedChange={(valor) => {
                  setActivo(valor);
                  setDirty(true);
                }}
                aria-label="Enviar el informe semanal"
              />
              {activo ? "Se envía cada semana" : "No se envía"}
            </label>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label htmlFor="informe-dia" className="text-sm font-medium">
                  Día
                </label>
                <Select
                  value={String(diaSemana)}
                  onValueChange={(valor) => {
                    setDiaSemana(Number(valor));
                    setDirty(true);
                  }}
                >
                  <SelectTrigger id="informe-dia" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DIAS.map((nombre, indice) => (
                      <SelectItem key={nombre} value={String(indice)}>
                        {nombre}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <label htmlFor="informe-hora" className="text-sm font-medium">
                  Hora (UTC)
                </label>
                <Select
                  value={String(horaUtc)}
                  onValueChange={(valor) => {
                    setHoraUtc(Number(valor));
                    setDirty(true);
                  }}
                >
                  <SelectTrigger id="informe-hora" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {HORAS.map((h) => (
                      <SelectItem key={h} value={String(h)}>
                        {String(h).padStart(2, "0")}:00
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* La pipeline corre cada cuatro horas: la hora programada es el
                momento a partir del cual sale, no el minuto exacto. Decirlo
                aquí evita el parte de incidencias de las 07:05. */}
            <p className="text-xs text-muted-foreground">
              En tu horario: <strong>{formatDiaYHora(proxima)}</strong>. Sale en la primera pasada
              posterior a esa hora, no en punto.
            </p>

            <div className="space-y-1.5">
              <label htmlFor="informe-destinatarios" className="text-sm font-medium">
                Destinatarios
              </label>
              <Textarea
                id="informe-destinatarios"
                rows={3}
                value={destinatarios}
                placeholder="Vacío = todos los owner y admin de la organización"
                onChange={(e) => {
                  setDestinatarios(e.target.value);
                  setDirty(true);
                }}
              />
              <p className="text-xs text-muted-foreground">
                Uno por línea. Déjalo vacío para que vaya a los owner y admin vigentes en cada
                envío —así dar de alta a un administrador nuevo no obliga a volver aquí—. Una lista
                explícita los sustituye y admite buzones que no son cuentas de la aplicación.
              </p>
            </div>

            {data?.ultimo_envio_at && (
              <p className="text-xs text-muted-foreground">
                Último envío: {formatDateTime(data.ultimo_envio_at)}
                {data.ultimo_estado ? ` — ${explicarEstado(data.ultimo_estado)}` : ""}
              </p>
            )}

            <Button size="sm" disabled={!dirty || guardar.isPending} onClick={enviar}>
              {guardar.isPending ? "Guardando…" : "Guardar programación"}
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}
