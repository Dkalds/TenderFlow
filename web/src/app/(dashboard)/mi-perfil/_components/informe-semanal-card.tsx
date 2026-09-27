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
 * organización, no del usuario, editable sólo por propietarios y administradores.
 *
 * La hora se guarda en **UTC** (el scheduler razona en UTC de punta a punta,
 * ADR-033) y aquí se traduce al enseñarla. La traducción se calcula sobre la
 * *próxima* entrega y no sobre una semana de referencia fija: así el horario
 * de verano sale bien en vez de con una hora de más medio año.
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Panel, PanelError, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useActiveOrganizationId, useOrganizations } from "@/hooks/use-organization";
import { DIAS, useGuardarReportSchedule, useReportSchedule } from "@/hooks/use-report-schedule";
import { getErrorMessage } from "@/lib/query-feedback";
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
      ? `Enviado a ${total} ${total === "1" ? "destinatario" : "destinatarios"}`
      : `Enviado a ${salieron} de ${total}; los demás correos se rechazaron`;
  }
  if (estado === "vacio") return "No se envió: esa semana no había nada que contar";
  if (estado === "sin_destinatarios") return "No se envió: no había ningún destinatario con correo";
  if (estado === "fallido") return "No salió ninguno: falló el proveedor de correo";
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
  const { data, isLoading, error, refetch } = useReportSchedule(organizationId);
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
            ? `Informe programado. Próximo envío: ${formatDiaYHora(proxima)}.`
            : "Informe semanal desactivado.",
        );
      })
      .catch((error: unknown) => toast.error(getErrorMessage(error, "accion")));
  };

  return (
    <Panel>
      <PanelTitle title="Informe semanal por correo" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        El resumen semanal de Dirección (embudo abierto, plazos a catorce días, ganadas y perdidas) por correo, con
        el mismo contenido en PDF. Está desactivado hasta que lo actives.
      </p>
      <div className="space-y-4">
        {isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : error ? (
          // Sin la programación leída, el formulario enseñaría «No se envía» y
          // los valores por defecto como si fueran los guardados.
          <PanelError
            variant="inline"
            title="No se pudo leer la programación del informe"
            error={error}
            onRetry={() => void refetch()}
          />
        ) : (
          <>
            <label className="flex items-center gap-3 text-tf-body">
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
              <Field label="Día" htmlFor="informe-dia">
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
              </Field>

              <Field label="Hora (UTC)" htmlFor="informe-hora">
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
              </Field>
            </div>

            {/* La pipeline corre cada cuatro horas: la hora programada es el
                momento a partir del cual sale, no el minuto exacto. Decirlo
                aquí evita el parte de incidencias de las 07:05. */}
            <p className="text-tf-meta text-muted-foreground">
              En tu horario: <strong className="font-medium text-foreground">{formatDiaYHora(proxima)}</strong>. Se
              envía a partir de esa hora y puede tardar hasta cuatro horas.
            </p>

            <Field
              label="Destinatarios"
              htmlFor="informe-destinatarios"
              hint="Uno por línea. Déjalo vacío para que llegue a los propietarios y administradores que haya en cada envío. Si escribes direcciones, solo se envía a esas, aunque no sean cuentas de TenderFlow."
            >
              <Textarea
                id="informe-destinatarios"
                rows={3}
                value={destinatarios}
                placeholder="Vacío = todos los propietarios y administradores de la organización"
                onChange={(e) => {
                  setDestinatarios(e.target.value);
                  setDirty(true);
                }}
              />
            </Field>

            {data?.ultimo_envio_at && (
              <p className="text-tf-meta text-muted-foreground">
                Último envío: {formatDateTime(data.ultimo_envio_at)}
                {data.ultimo_estado ? ` · ${explicarEstado(data.ultimo_estado)}` : ""}
              </p>
            )}

            <Button size="sm" disabled={!dirty || guardar.isPending} onClick={enviar}>
              {guardar.isPending ? "Guardando…" : "Guardar programación"}
            </Button>
          </>
        )}
      </div>
    </Panel>
  );
}
