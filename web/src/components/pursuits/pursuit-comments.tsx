"use client";

import * as React from "react";
import { Loader2, MessageSquare, SendHorizontal, Trash2, UserRound } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { PanelEmpty, PanelError } from "@/components/console/panel";
import {
  type PursuitComment,
  useAddPursuitComment,
  useDeletePursuitComment,
  usePursuitComments,
} from "@/hooks/use-pursuit-comments";
import type { Pursuit } from "@/hooks/use-pursuits";
import { useSession } from "@/lib/auth";
import { cn, formatDateTime, formatRelativeTime } from "@/lib/utils";

/**
 * Conversación del equipo sobre una oportunidad.
 *
 * Es un hilo, no un formulario: los mensajes van en orden cronológico con su
 * autor y su hora, el cuadro de escritura vive abajo y siempre a la vista, y
 * el hilo se refresca solo mientras está abierto (ver el hook). El mismo
 * componente sirve en la pestaña «Conversación» de la ficha y en el panel
 * lateral que se abre desde cada tarjeta del tablero: el equipo comenta sin
 * salir de `/oportunidades`.
 *
 * Lo que aquí NO se decide: quién puede borrar. Viene por comentario en
 * `can_delete` (autor, o owner/admin del espacio) y el botón solo se pinta
 * cuando la API lo permite.
 */

/** Mismo tope que `PURSUIT_COMMENT_MAX_CHARS` en `shared/dto.py`. */
export const COMMENT_MAX_CHARS = 4000;

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function authorLabel(comment: PursuitComment): string {
  if (comment.author_name) return comment.author_name;
  if (comment.author_user_id != null) return `Usuario ${comment.author_user_id}`;
  // Cuenta anonimizada (RGPD): el texto sigue siendo del equipo, el autor no.
  return "Antiguo miembro";
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "");
  return letters.join("") || "?";
}

function CommentAvatar({ comment }: { comment: PursuitComment }) {
  const anonymous = comment.author_user_id == null;
  return (
    <span
      aria-hidden="true"
      className={cn(
        "grid h-7 w-7 flex-none place-items-center rounded-full font-mono text-[10px] font-semibold",
        anonymous
          ? "bg-muted-foreground/12 text-muted-foreground"
          : "bg-primary/12 text-primary",
      )}
    >
      {anonymous ? <UserRound className="h-3.5 w-3.5" /> : initials(authorLabel(comment))}
    </span>
  );
}

function CommentItem({
  comment,
  mine,
  onDelete,
  deleting,
}: {
  comment: PursuitComment;
  mine: boolean;
  onDelete: () => void;
  deleting: boolean;
}) {
  // Borrado en dos pasos y dentro del propio mensaje: sin diálogo modal, pero
  // sin que un clic perdido se lleve un comentario de un compañero.
  const [confirming, setConfirming] = React.useState(false);
  const name = authorLabel(comment);

  return (
    <li className="flex gap-2.5 px-1 py-2">
      <CommentAvatar comment={comment} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="truncate text-[12px] font-semibold">{name}</span>
          {mine && (
            <span className="rounded bg-primary/12 px-1 py-px font-mono text-[9px] font-medium uppercase tracking-[0.08em] text-primary">
              tú
            </span>
          )}
          <time
            dateTime={comment.created_at}
            title={formatDateTime(comment.created_at)}
            className="text-[10.5px] text-muted-foreground"
          >
            {formatRelativeTime(comment.created_at)}
          </time>
          <div className="flex-1" />
          {comment.can_delete && !confirming && (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              disabled={deleting}
              aria-label="Borrar comentario"
              className="tf-pressable grid h-6 w-6 place-items-center rounded-md text-muted-foreground/70 transition-colors hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}
        </div>
        <p className="mt-0.5 whitespace-pre-wrap break-words text-[12.5px] leading-[1.55]">
          {comment.body}
        </p>
        {confirming && (
          <div
            role="group"
            aria-label="Confirmar borrado"
            className="mt-1.5 flex items-center gap-1.5 text-[11px]"
          >
            <span className="text-muted-foreground">¿Borrar este comentario?</span>
            <Button
              type="button"
              size="sm"
              variant="destructive"
              className="h-6 px-2 text-[11px]"
              disabled={deleting}
              onClick={() => {
                setConfirming(false);
                onDelete();
              }}
            >
              Borrar
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-6 px-2 text-[11px]"
              onClick={() => setConfirming(false)}
            >
              Cancelar
            </Button>
          </div>
        )}
      </div>
    </li>
  );
}

function CommentComposer({ pursuitId, onSent }: { pursuitId: number; onSent?: () => void }) {
  const add = useAddPursuitComment(pursuitId);
  const [draft, setDraft] = React.useState("");
  // Una clave por borrador: se renueva solo cuando el envío tiene éxito, así
  // que reintentar tras un fallo de red no duplica el mensaje.
  const keyRef = React.useRef<string>(newIdempotencyKey());
  const inputId = `pursuit-${pursuitId}-comment`;
  const trimmed = draft.trim();
  const tooLong = trimmed.length > COMMENT_MAX_CHARS;
  const canSend = trimmed.length > 0 && !tooLong && !add.isPending;

  const send = async () => {
    if (!canSend) return;
    try {
      await add.mutateAsync({ body: trimmed, idempotencyKey: keyRef.current });
      setDraft("");
      keyRef.current = newIdempotencyKey();
      onSent?.();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "No se pudo publicar el comentario");
    }
  };

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void send();
      }}
      className="flex-none border-t border-border/60 bg-background/95 pt-3"
    >
      <label className="sr-only" htmlFor={inputId}>
        Escribe un comentario para el equipo
      </label>
      <Textarea
        id={inputId}
        value={draft}
        rows={2}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
            event.preventDefault();
            void send();
          }
        }}
        placeholder="Escribe un comentario para el equipo…"
        aria-invalid={tooLong || undefined}
        className="min-h-[56px] resize-y text-[12.5px]"
      />
      <div className="mt-2 flex items-center gap-3">
        <span className="text-[10.5px] text-muted-foreground">
          Ctrl + Intro para publicar
        </span>
        {trimmed.length > COMMENT_MAX_CHARS * 0.8 && (
          <span
            className={cn(
              "tf-tnum font-mono text-[10.5px]",
              tooLong ? "text-destructive" : "text-muted-foreground",
            )}
          >
            {trimmed.length}/{COMMENT_MAX_CHARS}
          </span>
        )}
        <div className="flex-1" />
        <Button type="submit" size="sm" disabled={!canSend}>
          {add.isPending ? (
            <Loader2 className="animate-spin" aria-hidden="true" />
          ) : (
            <SendHorizontal aria-hidden="true" />
          )}
          Publicar
        </Button>
      </div>
    </form>
  );
}

/** Hilo completo: mensajes en orden cronológico y el cuadro para escribir. */
export function PursuitCommentsThread({
  pursuitId,
  className,
}: {
  pursuitId: number;
  className?: string;
}) {
  const thread = usePursuitComments(pursuitId);
  const remove = useDeletePursuitComment(pursuitId);
  const { user } = useSession();
  const myUserId = user ? Number(user.user_id) : null;
  const listRef = React.useRef<HTMLDivElement>(null);
  const items = React.useMemo(() => thread.data?.items ?? [], [thread.data]);
  const hidden = Math.max(0, (thread.data?.total ?? 0) - items.length);

  const scrollToEnd = React.useCallback(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, []);

  // Al abrir el hilo se muestra el final, que es donde está lo último; los
  // refrescos periódicos no mueven el scroll para no arrancar de la lectura a
  // quien subió a leer algo anterior.
  const scrolledOnLoad = React.useRef(false);
  React.useEffect(() => {
    if (thread.isSuccess && !scrolledOnLoad.current) {
      scrolledOnLoad.current = true;
      scrollToEnd();
    }
  }, [thread.isSuccess, scrollToEnd]);

  const deleteComment = async (commentId: number) => {
    try {
      await remove.mutateAsync(commentId);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "No se pudo borrar el comentario");
    }
  };

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div
        ref={listRef}
        className="min-h-0 flex-1 overflow-y-auto pb-3"
        aria-busy={thread.isLoading || undefined}
      >
        {thread.isLoading ? (
          <div className="space-y-3 px-1 py-2" aria-hidden="true">
            <Skeleton className="h-10 w-3/4 rounded-lg" />
            <Skeleton className="h-10 w-2/3 rounded-lg" />
            <Skeleton className="h-10 w-4/5 rounded-lg" />
          </div>
        ) : thread.error ? (
          <PanelError
            title="No se pudo cargar la conversación"
            detail={(thread.error as Error).message}
            onRetry={() => void thread.refetch()}
          />
        ) : items.length === 0 ? (
          <PanelEmpty message="Todavía no hay comentarios. Deja aquí lo que el equipo tiene que saber de esta oportunidad." />
        ) : (
          <>
            {hidden > 0 && (
              <p className="px-1 pb-1 text-[10.5px] text-muted-foreground">
                Se muestran los {items.length} comentarios más recientes de {thread.data?.total}.
              </p>
            )}
            <ol className="divide-y divide-border/40" aria-label="Comentarios">
              {items.map((comment) => (
                <CommentItem
                  key={comment.id}
                  comment={comment}
                  mine={myUserId != null && comment.author_user_id === myUserId}
                  deleting={remove.isPending && remove.variables === comment.id}
                  onDelete={() => void deleteComment(comment.id)}
                />
              ))}
            </ol>
          </>
        )}
      </div>
      <CommentComposer pursuitId={pursuitId} onSent={scrollToEnd} />
    </div>
  );
}

/** Panel lateral con el hilo, para comentar sin salir del tablero. */
export function PursuitCommentsSheet({
  pursuit,
  open,
  onOpenChange,
}: {
  pursuit: Pursuit;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-md">
        <SheetHeader className="flex-none border-b border-border/60 px-4 pb-3 pt-4 text-left">
          <SheetTitle className="pr-8 text-[14px] leading-snug text-pretty">
            {pursuit.tender_title ?? `Licitación ${pursuit.licitacion_id}`}
          </SheetTitle>
          <SheetDescription className="text-[11px]">
            Conversación del equipo · Referencia{" "}
            <span className="font-mono text-foreground/80">{pursuit.licitacion_id}</span>
          </SheetDescription>
        </SheetHeader>
        {/* Solo montado mientras está abierto: así el hilo no se refresca en
            segundo plano por cada tarjeta del tablero. El foco al abrir lo
            gestiona el propio Sheet (Radix): sin `autoFocus` a mano. */}
        {open && (
          <PursuitCommentsThread pursuitId={pursuit.id} className="min-h-0 flex-1 px-4 pb-4 pt-2" />
        )}
      </SheetContent>
    </Sheet>
  );
}

/** Botón de la tarjeta del tablero: cuenta el hilo y lo abre en el panel lateral. */
export function PursuitCommentsButton({ pursuit }: { pursuit: Pursuit }) {
  const [open, setOpen] = React.useState(false);
  const count = pursuit.comments_count ?? 0;
  const label =
    count === 0
      ? "Comentar"
      : count === 1
        ? "1 comentario"
        : `${count} comentarios`;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`Abrir la conversación del equipo (${label})`}
        className={cn(
          "tf-pressable inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-xs font-medium transition-colors",
          count > 0
            ? "text-primary hover:bg-primary/10"
            : "text-muted-foreground hover:bg-muted hover:text-foreground",
        )}
      >
        <MessageSquare className="h-3.5 w-3.5" aria-hidden="true" />
        <span className="tf-tnum">{count > 0 ? count : "Comentar"}</span>
      </button>
      <PursuitCommentsSheet pursuit={pursuit} open={open} onOpenChange={setOpen} />
    </>
  );
}
