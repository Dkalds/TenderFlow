"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronRight, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { Aviso, PanelError } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, MENSAJE_SIN_CONEXION, mensajePorEstado } from "@/lib/api-client";
import { detalleTecnico } from "@/lib/query-feedback";
import { FeedbackButtons } from "@/components/feedback-buttons";
import { MarkdownAnswer } from "@/components/markdown-answer";
import type { ChatTurn } from "@/hooks/use-ask";
import type { AskMeta, DegradedInfo, FuenteDocumento, SourcesInfo } from "@/lib/ask-stream";

/**
 * Mensaje humano para el fallo de una llamada del asistente. `ask-stream` lanza
 * un `ApiError` con el estado HTTP y el `detail` de la API, o el error de red
 * del navegador: ni uno ni otro se enseñan tal cual (D6). Del `ApiError` solo
 * cuenta el estado: su `detail` («CSRF token mismatch», el presupuesto agotado
 * con sus importes) es para soporte y va al «Detalle técnico» plegado de
 * `PanelError`, con `detalleDeFalloIA`.
 */
export function mensajeDeFalloIA(error: unknown): string {
  if (error instanceof ApiError) return mensajePorEstado(error.status);
  if (error instanceof Error && /failed to fetch|networkerror|load failed/i.test(error.message)) {
    return MENSAJE_SIN_CONEXION;
  }
  return "El asistente no pudo responder. Vuelve a intentarlo en unos segundos.";
}

/**
 * Lo que va plegado bajo `mensajeDeFalloIA`: estado, método y ruta, y el
 * `detail` que mandó la API. Es lo que distingue un 403 de otro.
 */
export function detalleDeFalloIA(error: unknown): string | undefined {
  return detalleTecnico(error, mensajeDeFalloIA(error));
}

/**
 * Etiqueta de lo que escribe el asistente (F07, ADR-014): una respuesta de
 * modelo no es un dato del expediente, y se dice debajo de cada una. En la
 * ficha de una licitación hay un pliego al que remitir; en el Investigador y
 * el copiloto, los de los expedientes citados.
 */
export const AVISO_GENERADO = "Generado automáticamente · revisa el pliego";
const AVISO_GENERADO_VARIOS = "Generado automáticamente · revisa los pliegos citados";

/** Bloque plegable con los fragmentos del pliego que se mandaron al modelo en un turno. */
function FuentesBlock({ fuentes }: { fuentes: FuenteDocumento[] }) {
  const [open, setOpen] = React.useState(false);
  const idFuentes = React.useId();
  const totalChunks = fuentes.reduce((n, f) => n + (f.chunks?.length ?? 0), 0);
  if (totalChunks === 0) return null;

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={idFuentes}
        className="flex items-center gap-1 rounded-sm text-tf-meta font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronRight className={cn("h-3 w-3 transition-[rotate]", open && "rotate-90")} aria-hidden="true" />
        Fuentes del pliego ({totalChunks})
      </button>
      {/* Grid-rows trick: animates height without measuring it, and stays
          interruptible if the user toggles again mid-transition. */}
      <div
        id={idFuentes}
        inert={!open}
        className={cn(
          "grid transition-[grid-template-rows] duration-200 ease-out",
          open ? "mt-2 grid-rows-[1fr]" : "grid-rows-[0fr]"
        )}
      >
        <div className="overflow-hidden">
          <div className="space-y-2">
            {fuentes.map((f, i) => (
              <div key={`${f.id_externo}-${i}`} className="rounded-md border border-border bg-muted/40 p-2">
                <div className="mb-1 text-tf-meta font-medium">
                  {f.id_externo ? (
                    <Link
                      href={`/detalle?lic=${encodeURIComponent(f.id_externo)}`}
                      className="font-mono text-primary hover:underline"
                    >
                      {f.id_externo}
                    </Link>
                  ) : null}
                  {f.titulo ? <span className="text-muted-foreground"> — {f.titulo}</span> : null}
                </div>
                {f.chunks?.map((c, j) => (
                  <blockquote key={j} className="mt-1 border-l-2 border-border pl-2 text-tf-meta text-muted-foreground">
                    {(c.tipo || c.filename) && (
                      <span className="font-medium">[{[c.tipo, c.filename].filter(Boolean).join(" · ")}] </span>
                    )}
                    {c.texto}
                  </blockquote>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Citas validadas de un turno (C5.3). El backend ya descartó las que apuntaban
 * a documentos ausentes del contexto, así que lo que se pinta aquí se sostiene.
 *
 * Se listan aparte de `FuentesBlock`: aquel enseña **todo** lo que se le mandó
 * al modelo, y esto enseña lo que el modelo **usó**. Mezclarlos haría creer que
 * la respuesta se apoya en catorce fragmentos cuando citó dos.
 */
function CitasBlock({ info }: { info: SourcesInfo }) {
  if (info.sources.length === 0) return null;
  return (
    <div className="mt-2 space-y-1">
      <p className="text-tf-meta font-medium text-muted-foreground">
        Citado del pliego ({info.sources.length})
      </p>
      {info.sources.map((f, i) => (
        <blockquote
          key={`${f.documento_id}-${f.page_number ?? "s"}-${i}`}
          className="border-l-2 border-border pl-2 text-tf-meta text-muted-foreground"
        >
          <span className="text-foreground font-medium">
            {f.id_externo ? `${f.id_externo} · ` : ""}
            {[f.tipo, f.filename].filter(Boolean).join(" · ") || `Documento ${f.documento_id}`}
            {f.page_number != null ? `, p. ${f.page_number}` : ""}
          </span>
          <span className="block">{f.cita}</span>
        </blockquote>
      ))}
    </div>
  );
}

/**
 * La respuesta no se apoya en ningún fragmento del pliego (C5.3 / D29).
 *
 * Se pinta distinto a propósito: una respuesta sin fuentes y una con ellas se
 * leen igual de seguras, y esa es exactamente la confusión que la cita viene a
 * evitar. No dice que la respuesta sea falsa — dice que el pliego no la
 * sostiene, que es lo que se sabe.
 */
function SinFuentesNotice() {
  return (
    <p className="mt-2 flex items-start gap-1.5 text-tf-meta text-muted-foreground">
      <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
      <span>Sin fuentes en el pliego: esta respuesta no cita ningún fragmento de los documentos.</span>
    </p>
  );
}

/** Aviso: se pidió contexto de una licitación pero la respuesta salió del
 *  resto de licitaciones (no se pudo cargar el expediente). Sin esto el
 *  fallback era silencioso y la respuesta se leía como si fuera del pliego. */
function ScopeFallbackNotice() {
  return (
    <Aviso tone="warning" title="Respuesta sin el contexto de este expediente" className="mt-2">
      No se pudo cargar la licitación (o sus pliegos), así que esta respuesta se basa en el resto de
      licitaciones y en conocimiento general.
    </Aviso>
  );
}

/**
 * F2.8 — lo que de verdad entró en una pregunta cruzada.
 *
 * Una comparación en la que uno de los tres expedientes no cargó, o llegó con
 * su parte del pliego recortada, se leería como una comparación de tres. El
 * backend lo declara en `ask_meta`; aquí se dice con nombre.
 */
function ComparacionNotice({ meta }: { meta: AskMeta }) {
  const expedientes = meta.expedientes ?? [];
  const ausentes = expedientes.filter((e) => !e.encontrado).map((e) => e.id_externo);
  const recortados = expedientes.filter((e) => e.encontrado && e.truncado).map((e) => e.id_externo);
  const sinPliego = expedientes
    .filter((e) => e.encontrado && e.has_pliego_text === false)
    .map((e) => e.id_externo);
  if (ausentes.length === 0 && recortados.length === 0 && sinPliego.length === 0) return null;
  return (
    <Aviso tone="warning" title="Comparación incompleta" className="mt-2">
      {ausentes.length > 0 && <p>No se pudo cargar: {ausentes.join(", ")}.</p>}
      {sinPliego.length > 0 && <p>Solo con el anuncio, sin pliegos: {sinPliego.join(", ")}.</p>}
      {recortados.length > 0 && <p>Pliego recortado para que quepan todos: {recortados.join(", ")}.</p>}
    </Aviso>
  );
}

/** Aviso cuando el asistente no pudo sintetizar respuesta (modo degradado). */
function DegradedNotice({ degraded }: { degraded: DegradedInfo }) {
  const docs = degraded.docs ?? [];
  return (
    <Aviso
      tone="warning"
      className="mt-2"
      title={`El asistente no está disponible ahora mismo${degraded.reason === "timeout" ? " (tardó demasiado en responder)" : ""}.`}
    >
      {docs.length > 0 && (
        <div className="space-y-1">
          <p>Licitaciones encontradas para tu consulta:</p>
          <ul className="list-disc space-y-0.5 pl-4">
            {docs.map((d, i) => (
              <li key={i}>
                <Link
                  href={`/detalle?lic=${encodeURIComponent(String(d.id_externo ?? ""))}`}
                  className="text-primary hover:underline"
                >
                  {String(d.titulo ?? d.id_externo ?? "Licitación")}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Aviso>
  );
}

export interface ChatThreadProps {
  messages: ChatTurn[];
  streaming: boolean;
  loading: boolean;
  error: Error | null;
  className?: string;
  /**
   * True cuando este hilo pidió contexto de una licitación concreta
   * (`idExterno`): habilita el aviso de fallback si la respuesta salió del
   * resto de licitaciones en su lugar.
   */
  expectLicitacionContext?: boolean;
}

interface TurnoAsistenteProps {
  turno: ChatTurn;
  /** La pregunta que lo originó: la hashea el voto de los pulgares. */
  pregunta: string | undefined;
  /** Último turno sin su primer token todavía: esqueleto en vez de burbuja vacía. */
  esperandoPrimerToken: boolean;
  /** Último turno con el stream abierto: cursor al final del texto. */
  emitiendo: boolean;
  /** Último turno con la respuesta en curso: aún no se puede votar. */
  enCurso: boolean;
  expectLicitacionContext?: boolean;
}

/**
 * Un turno del asistente.
 *
 * `memo` porque mientras la última respuesta se emite el hilo entero se repinta
 * en cada frame, y los turnos anteriores —el mismo objeto, las mismas banderas—
 * no tienen nada que repintar: solo el último recibe props nuevas.
 */
const TurnoAsistente = React.memo(function TurnoAsistente({
  turno,
  pregunta,
  esperandoPrimerToken,
  emitiendo,
  enCurso,
  expectLicitacionContext,
}: TurnoAsistenteProps) {
  // El hilo entero es de un expediente (la ficha), o este turno se pidió sobre
  // uno concreto (el Investigador, donde el alcance cambia de un turno a otro).
  // Con varios pedidos, lo que faltó lo dice `ComparacionNotice`.
  const esperaExpediente = expectLicitacionContext || turno.expedientesPedidos?.length === 1;
  return (
    <div className="text-tf-body">
      {turno.content ? (
        <MarkdownAnswer text={turno.content} />
      ) : esperandoPrimerToken ? (
        <div className="space-y-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
        </div>
      ) : null}
      {emitiendo && turno.content ? (
        <span className="text-primary motion-safe:animate-pulse" aria-hidden="true">
          ▌
        </span>
      ) : null}
      {esperaExpediente && turno.askMeta && turno.askMeta.contexto === "general" ? (
        <ScopeFallbackNotice />
      ) : null}
      {turno.askMeta?.expedientes ? <ComparacionNotice meta={turno.askMeta} /> : null}
      {turno.degraded ? <DegradedNotice degraded={turno.degraded} /> : null}
      {turno.sources ? <CitasBlock info={turno.sources} /> : null}
      {turno.sources?.sinFuentes ? <SinFuentesNotice /> : null}
      {turno.fuentes && turno.fuentes.length > 0 ? <FuentesBlock fuentes={turno.fuentes} /> : null}
      {turno.content && !turno.degraded && !enCurso ? (
        <>
          <p className="mt-2 text-tf-micro text-muted-foreground">
            {esperaExpediente ? AVISO_GENERADO : AVISO_GENERADO_VARIOS}
          </p>
          <FeedbackButtons modo="pregunta" pregunta={pregunta} />
        </>
      ) : null}
    </div>
  );
});

/**
 * Presentational multi-turn chat thread (shared by the copilot panel, the
 * investigador page and the licitación AI tab). Inputs live in the parents.
 */
export function ChatThread({
  messages,
  streaming,
  loading,
  error,
  className,
  expectLicitacionContext,
}: ChatThreadProps) {
  const bottomRef = React.useRef<HTMLDivElement>(null);

  // Como mucho un scroll por frame. `scrollIntoView` fuerza un layout, y con
  // una respuesta emitiéndose `messages` cambia sin parar: el scroll se
  // programa para el frame siguiente y un cambio posterior dentro del mismo
  // frame lo sustituye en vez de sumarle otro.
  React.useEffect(() => {
    const frame = requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ block: "end" }));
    return () => cancelAnimationFrame(frame);
  }, [messages]);

  const last = messages[messages.length - 1];
  const waitingFirstToken = loading && last?.role === "assistant" && !last.content;

  return (
    <div className={cn("space-y-3", className)}>
      {messages.map((m, i) => {
        if (m.role === "user") {
          return (
            <div key={i} className="flex justify-end">
              <div className="max-w-[85%] rounded-xl bg-muted px-3 py-2 text-tf-body whitespace-pre-wrap">{m.content}</div>
            </div>
          );
        }
        const isLast = i === messages.length - 1;
        return (
          <TurnoAsistente
            key={i}
            turno={m}
            pregunta={messages[i - 1]?.content}
            esperandoPrimerToken={isLast && waitingFirstToken}
            emitiendo={isLast && streaming}
            enCurso={isLast && (streaming || loading)}
            expectLicitacionContext={expectLicitacionContext}
          />
        );
      })}

      {/* Un solo aviso: el hilo no pasa por React Query, así que no hay toast
          que callar. Mensaje humano; lo que dijo la API, plegado. */}
      {error && (
        <PanelError
          variant="inline"
          title="No se pudo obtener la respuesta"
          message={mensajeDeFalloIA(error)}
          detail={detalleDeFalloIA(error)}
        />
      )}
      <div ref={bottomRef} />
    </div>
  );
}
