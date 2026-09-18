"use client";

import * as React from "react";
import { Check, CircleDollarSign, Loader2, Save } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { type Pursuit, type PursuitDecision, type PursuitOutcome, type PursuitStatus, useUpdatePursuit } from "@/hooks/use-pursuits";
import { useOrganizationMembers } from "@/hooks/use-organization";
import { PursuitDecisionBadge, PursuitOutcomeBadge, PursuitStatusBadge } from "@/components/pursuits/pursuit-presenters";
import { MOTIVOS_PERDIDA, type MotivoPerdida, errorDeCierre, esMotivoPerdida, pideCodificar } from "@/lib/motivos-perdida";

const statuses: Array<{ value: PursuitStatus; label: string }> = [
  { value: "identified", label: "Identificada" }, { value: "qualifying", label: "En cualificación" },
  { value: "go_no_go", label: "Decisión GO/NO-GO" }, { value: "preparing", label: "Preparando oferta" },
  { value: "submitted", label: "Oferta presentada" }, { value: "won", label: "Ganada" },
  { value: "lost", label: "Perdida" }, { value: "withdrawn", label: "Retirada" },
];

interface FormState {
  status: PursuitStatus;
  responsible_user_id: string;
  decision: PursuitDecision;
  decision_reason: string;
  offer_price_eur: string;
  outcome: PursuitOutcome;
  awarded_amount_eur: string;
  outcome_reason: string;
  /** F3.1 — código de D37; vacío = sin elegir. */
  outcome_reason_code: MotivoPerdida | "";
}

function formFrom(pursuit: Pursuit): FormState {
  return {
    status: pursuit.status,
    responsible_user_id: pursuit.responsible_user_id?.toString() ?? "",
    decision: pursuit.decision,
    decision_reason: pursuit.decision_reason ?? "",
    offer_price_eur: pursuit.offer_price_eur?.toString() ?? "",
    outcome: pursuit.outcome,
    awarded_amount_eur: pursuit.awarded_amount_eur?.toString() ?? "",
    outcome_reason: pursuit.outcome_reason ?? "",
    outcome_reason_code: pursuit.outcome_reason_code ?? "",
  };
}

function moneyOrNull(value: string): number | null {
  const normalized = value.trim().replace(",", ".");
  if (!normalized) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

/** The operational form keeps the canonical business dimensions visibly separate. */
export function PursuitEditor({ pursuit }: { pursuit: Pursuit }) {
  return <PursuitEditorForm key={`${pursuit.id}:${pursuit.version}`} pursuit={pursuit} />;
}

function PursuitEditorForm({ pursuit }: { pursuit: Pursuit }) {
  const update = useUpdatePursuit(pursuit.id);
  const members = useOrganizationMembers(pursuit.organization_id).data ?? [];
  const [form, setForm] = React.useState<FormState>(() => formFrom(pursuit));
  const [intentado, setIntentado] = React.useState(false);
  const errorMotivo = errorDeCierre(form.outcome, form.outcome_reason_code, form.outcome_reason);

  const save = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIntentado(true);
    if (errorMotivo) {
      toast.error(errorMotivo);
      return;
    }
    try {
      await update.mutateAsync({
        status: form.status,
        responsible_user_id: form.responsible_user_id.trim() ? Number(form.responsible_user_id) : null,
        decision: form.decision,
        decision_reason: form.decision_reason.trim() || null,
        offer_price_eur: moneyOrNull(form.offer_price_eur),
        outcome: form.outcome,
        awarded_amount_eur: moneyOrNull(form.awarded_amount_eur),
        outcome_reason: form.outcome_reason.trim() || null,
        // Sólo viaja al cerrar (o completar) una pérdida: en cualquier otro
        // resultado el código no significa nada y no se toca.
        ...(form.outcome === "lost" && form.outcome_reason_code
          ? { outcome_reason_code: form.outcome_reason_code }
          : {}),
        expected_version: pursuit.version,
      });
      toast.success("Oportunidad actualizada");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "No se pudo guardar la oportunidad");
    }
  };

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((current) => ({ ...current, [key]: value }));
  const inputId = (name: string) => `pursuit-${pursuit.id}-${name}`;

  return (
    <form onSubmit={save} className="space-y-4">
      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
          <div><CardTitle className="flex items-center gap-2"><Check className="h-4 w-4 text-primary" />Decisión y avance</CardTitle><p className="mt-1 text-sm text-muted-foreground">El estado no sustituye la decisión de negocio.</p></div>
          <PursuitStatusBadge status={form.status} />
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1.5 text-sm font-medium" htmlFor={inputId("status")}>Estado
            <Select value={form.status} onValueChange={(value) => set("status", value as PursuitStatus)}><SelectTrigger id={inputId("status")}><SelectValue /></SelectTrigger><SelectContent>{statuses.map((status) => <SelectItem key={status.value} value={status.value}>{status.label}</SelectItem>)}</SelectContent></Select>
          </label>
          <label className="space-y-1.5 text-sm font-medium" htmlFor={inputId("owner")}>Responsable
            <Select
              value={form.responsible_user_id || "unassigned"}
              onValueChange={(value) => set("responsible_user_id", value === "unassigned" ? "" : value)}
            >
              <SelectTrigger id={inputId("owner")}><SelectValue placeholder="Sin asignar" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="unassigned">Sin asignar</SelectItem>
                {members.map((member) => (
                  <SelectItem key={member.user_id} value={String(member.user_id)}>
                    {member.display_name ?? member.email ?? `Usuario ${member.user_id}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="block text-xs font-normal text-muted-foreground">Asigna una persona de tu organización.</span>
          </label>
          <label className="space-y-1.5 text-sm font-medium" htmlFor={inputId("decision")}>Decisión
            <Select value={form.decision} onValueChange={(value) => set("decision", value as PursuitDecision)}><SelectTrigger id={inputId("decision")}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="pending">Pendiente</SelectItem><SelectItem value="go">GO</SelectItem><SelectItem value="no_go">NO-GO</SelectItem></SelectContent></Select>
            <PursuitDecisionBadge decision={form.decision} />
          </label>
          <label className="space-y-1.5 text-sm font-medium" htmlFor={inputId("decision-reason")}>Motivo
            <Textarea id={inputId("decision-reason")} value={form.decision_reason} onChange={(event) => set("decision_reason", event.target.value)} placeholder="Qué evidencia sostiene la decisión" />
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3 space-y-0"><div><CardTitle className="flex items-center gap-2"><CircleDollarSign className="h-4 w-4 text-primary" />Oferta y resultado</CardTitle><p className="mt-1 text-sm text-muted-foreground">Separamos importe ofertado, resultado y adjudicación.</p></div><PursuitOutcomeBadge outcome={form.outcome} /></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1.5 text-sm font-medium" htmlFor={inputId("offer-price")}>Precio ofertado (€)
            <Input id={inputId("offer-price")} inputMode="decimal" value={form.offer_price_eur} onChange={(event) => set("offer_price_eur", event.target.value)} placeholder="Ej. 125000" />
          </label>
          <label className="space-y-1.5 text-sm font-medium" htmlFor={inputId("outcome")}>Resultado
            <Select value={form.outcome} onValueChange={(value) => {
              const outcome = value as PursuitOutcome;
              set("outcome", outcome);
              if (outcome === "won" || outcome === "lost") set("status", outcome);
              if (outcome === "cancelled") set("status", "withdrawn");
            }}><SelectTrigger id={inputId("outcome")}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="pending">Sin cerrar</SelectItem><SelectItem value="won">Ganada</SelectItem><SelectItem value="lost">Perdida</SelectItem><SelectItem value="cancelled">Cancelada</SelectItem></SelectContent></Select>
          </label>
          <label className="space-y-1.5 text-sm font-medium" htmlFor={inputId("awarded-price")}>Importe adjudicado (€)
            <Input id={inputId("awarded-price")} inputMode="decimal" value={form.awarded_amount_eur} onChange={(event) => set("awarded_amount_eur", event.target.value)} placeholder="Solo si se conoce" />
          </label>
          {form.outcome === "lost" && (
            <div className="space-y-1.5 text-sm font-medium sm:col-span-2">
              {pideCodificar(pursuit) && !form.outcome_reason_code ? (
                <p role="status" className="rounded-md border border-border/70 bg-muted/40 px-3 py-2 text-xs font-normal text-muted-foreground">
                  Este cierre es anterior a los motivos codificados y cuenta como «sin codificar» en el reparto de pérdidas. Elige el motivo para completarlo.
                </p>
              ) : null}
              <label htmlFor={inputId("outcome-reason-code")}>Motivo de la pérdida</label>
              <Select
                value={form.outcome_reason_code}
                onValueChange={(value) => set("outcome_reason_code", esMotivoPerdida(value) ? value : "")}
              >
                <SelectTrigger
                  id={inputId("outcome-reason-code")}
                  aria-required="true"
                  aria-invalid={intentado && Boolean(errorMotivo)}
                  aria-describedby={inputId("outcome-reason-code-ayuda")}
                >
                  <SelectValue placeholder="Elige un motivo" />
                </SelectTrigger>
                <SelectContent>
                  {MOTIVOS_PERDIDA.map((motivo) => (
                    <SelectItem key={motivo.codigo} value={motivo.codigo}>{motivo.etiqueta}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <span id={inputId("outcome-reason-code-ayuda")} className="block text-xs font-normal text-muted-foreground">
                {MOTIVOS_PERDIDA.find((motivo) => motivo.codigo === form.outcome_reason_code)?.ayuda ??
                  "Obligatorio al cerrar como perdida: es lo que permite saber por qué se pierde."}
              </span>
              {intentado && errorMotivo ? (
                <span role="alert" className="block text-xs font-normal text-destructive">{errorMotivo}</span>
              ) : null}
            </div>
          )}
          <label className="space-y-1.5 text-sm font-medium" htmlFor={inputId("outcome-reason")}>
            {form.outcome === "lost" && form.outcome_reason_code === "otro" ? "Nota de cierre (obligatoria con «Otro»)" : "Nota de cierre"}
            <Textarea id={inputId("outcome-reason")} value={form.outcome_reason} onChange={(event) => set("outcome_reason", event.target.value)} placeholder="Contexto del resultado o ausencia de importe" />
          </label>
        </CardContent>
      </Card>
      <div className="sticky bottom-4 z-10 flex justify-end"><Button type="submit" disabled={update.isPending}>{update.isPending ? <Loader2 className="animate-spin" /> : <Save />}Guardar cambios</Button></div>
    </form>
  );
}
