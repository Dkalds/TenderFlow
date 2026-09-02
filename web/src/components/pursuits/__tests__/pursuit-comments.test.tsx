import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  PursuitCommentsButton,
  PursuitCommentsThread,
} from "@/components/pursuits/pursuit-comments";
import type { PursuitComment } from "@/hooks/use-pursuit-comments";
import type { Pursuit } from "@/hooks/use-pursuits";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const state = {
  items: [] as PursuitComment[],
  total: 0,
  isLoading: false,
  error: null as Error | null,
};
const addMutate = vi.fn().mockResolvedValue({});
const deleteMutate = vi.fn().mockResolvedValue(undefined);
const refetch = vi.fn();

vi.mock("@/hooks/use-pursuit-comments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/use-pursuit-comments")>();
  return {
    ...actual,
    usePursuitComments: () => ({
      data:
        state.isLoading || state.error
          ? undefined
          : {
              pursuit_id: 1,
              organization_id: 1,
              items: state.items,
              total: state.total,
              limit: 200,
              offset: 0,
            },
      isLoading: state.isLoading,
      isSuccess: !state.isLoading && !state.error,
      error: state.error,
      refetch,
    }),
    useAddPursuitComment: () => ({ mutateAsync: addMutate, isPending: false }),
    useDeletePursuitComment: () => ({
      mutateAsync: deleteMutate,
      isPending: false,
      variables: undefined,
    }),
  };
});

// Quien mira el hilo es el usuario 5: sus comentarios llevan la marca «tú».
vi.mock("@/lib/auth", () => ({
  useSession: () => ({
    user: { user_id: "5", email: "ana@example.test", display_name: "Ana Gómez", is_admin: false },
    isLoading: false,
    isAuthenticated: true,
    isAdmin: false,
    refresh: vi.fn(),
  }),
}));

function comment(overrides: Partial<PursuitComment> = {}): PursuitComment {
  return {
    id: 1,
    pursuit_id: 1,
    organization_id: 1,
    author_user_id: 5,
    author_name: "Ana Gómez",
    body: "Primer comentario",
    created_at: "2026-09-01T10:00:00Z",
    can_delete: true,
    ...overrides,
  };
}

const basePursuit: Pursuit = {
  id: 1,
  organization_id: 1,
  licitacion_id: "lic-1",
  tender_title: "Servicio TI",
  tender_deadline: null,
  responsible_user_id: null,
  responsible_name: null,
  status: "identified",
  decision: "pending",
  decision_reason: null,
  offer_price_eur: null,
  outcome: "pending",
  awarded_amount_eur: null,
  outcome_reason: null,
  identified_at: "2026-07-30T10:00:00Z",
  decision_at: null,
  submitted_at: null,
  closed_at: null,
  created_at: "2026-07-30T10:00:00Z",
  updated_at: "2026-07-30T10:00:00Z",
  version: 1,
  comments_count: 0,
};

const composer = () => screen.getByLabelText("Escribe un comentario para el equipo");

beforeEach(() => {
  state.items = [];
  state.total = 0;
  state.isLoading = false;
  state.error = null;
});

afterEach(() => {
  addMutate.mockClear();
  deleteMutate.mockClear();
  refetch.mockClear();
});

describe("PursuitCommentsThread", () => {
  it("shows the empty state when the thread has no comments", () => {
    render(<PursuitCommentsThread pursuitId={1} />);

    expect(screen.getByRole("status")).toHaveTextContent("Todavía no hay comentarios");
  });

  it("lists comments with their author, marks mine and only offers delete when allowed", () => {
    state.items = [
      comment(),
      comment({ id: 2, author_user_id: 9, author_name: "Luis", body: "Segundo", can_delete: false }),
      comment({ id: 3, author_user_id: null, author_name: null, body: "Huérfano", can_delete: false }),
    ];
    state.total = 3;

    render(<PursuitCommentsThread pursuitId={1} />);

    expect(screen.getByText("Ana Gómez")).toBeInTheDocument();
    expect(screen.getByText("Luis")).toBeInTheDocument();
    expect(screen.getByText("Antiguo miembro")).toBeInTheDocument();
    expect(screen.getAllByText("tú")).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Borrar comentario" })).toHaveLength(1);
  });

  it("says how many comments are not shown when the thread is longer than the page", () => {
    state.items = [comment()];
    state.total = 5;

    render(<PursuitCommentsThread pursuitId={1} />);

    expect(screen.getByText(/más recientes de 5/)).toBeInTheDocument();
  });

  it("offers a retry when the thread cannot be loaded", () => {
    state.error = new Error("sin red");

    render(<PursuitCommentsThread pursuitId={1} />);

    fireEvent.click(screen.getByRole("button", { name: /Reintentar/ }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("publishes the trimmed draft with an idempotency key and clears the box", async () => {
    render(<PursuitCommentsThread pursuitId={1} />);
    const button = screen.getByRole("button", { name: /Publicar/ });
    expect(button).toBeDisabled();

    fireEvent.change(composer(), { target: { value: "  Vamos a por ella  " } });
    expect(button).toBeEnabled();
    fireEvent.click(button);

    await vi.waitFor(() => expect(addMutate).toHaveBeenCalledTimes(1));
    expect(addMutate.mock.calls[0][0]).toMatchObject({ body: "Vamos a por ella" });
    expect(typeof addMutate.mock.calls[0][0].idempotencyKey).toBe("string");
    await vi.waitFor(() => expect(composer()).toHaveValue(""));
  });

  it("sends with Ctrl+Enter and keeps the draft and its key when the send fails", async () => {
    addMutate.mockRejectedValueOnce(new Error("sin red"));
    render(<PursuitCommentsThread pursuitId={1} />);

    fireEvent.change(composer(), { target: { value: "hola" } });
    fireEvent.keyDown(composer(), { key: "Enter", ctrlKey: true });
    await vi.waitFor(() => expect(addMutate).toHaveBeenCalledTimes(1));
    expect(composer()).toHaveValue("hola");

    fireEvent.keyDown(composer(), { key: "Enter", ctrlKey: true });
    await vi.waitFor(() => expect(addMutate).toHaveBeenCalledTimes(2));

    // Mismo borrador, misma clave: el reintento no puede duplicar el mensaje.
    expect(addMutate.mock.calls[1][0].idempotencyKey).toBe(addMutate.mock.calls[0][0].idempotencyKey);
  });

  it("asks for confirmation before deleting a comment", async () => {
    state.items = [comment()];
    state.total = 1;
    render(<PursuitCommentsThread pursuitId={1} />);

    fireEvent.click(screen.getByRole("button", { name: "Borrar comentario" }));
    expect(deleteMutate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(deleteMutate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Borrar comentario" }));
    fireEvent.click(screen.getByRole("button", { name: "Borrar" }));
    await vi.waitFor(() => expect(deleteMutate).toHaveBeenCalledWith(1));
  });
});

describe("PursuitCommentsButton", () => {
  it("shows the count carried by the opportunity and opens the thread in a side panel", () => {
    render(<PursuitCommentsButton pursuit={{ ...basePursuit, comments_count: 3 }} />);

    fireEvent.click(screen.getByRole("button", { name: /3 comentarios/ }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Servicio TI");
    expect(dialog).toHaveTextContent("lic-1");
    expect(composer()).toBeInTheDocument();
  });

  it("invites to comment when the thread is empty", () => {
    render(<PursuitCommentsButton pursuit={basePursuit} />);

    expect(screen.getByRole("button", { name: /Comentar/ })).toBeInTheDocument();
  });
});
