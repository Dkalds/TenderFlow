/**
 * Tests del historial del ámbito (`lib/scope-history.ts`).
 *
 * Dos capas: el store de zustand (pila pura, sin React) y el hook observador,
 * que es donde vive la regla que de verdad importa — el historial se alimenta
 * mirando el ámbito, no los botones, así que también entra en la pila un
 * cross-filter o una vista guardada.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act, cleanup, waitFor } from "@testing-library/react";
import { withNuqsTestingAdapter } from "nuqs/adapters/testing";
import { useValorDiferido } from "@/hooks/use-valor-diferido";
import { EMPTY_SCOPE, scopeKey, useFilters, type ScopeSnapshot } from "@/lib/filters";
import { useScopeHistory, useScopeHistoryStore } from "@/lib/scope-history";

const scope = (overrides: Partial<ScopeSnapshot> = {}): ScopeSnapshot => ({
  ...EMPTY_SCOPE,
  ...overrides,
});

const resetStore = () =>
  useScopeHistoryStore.setState({
    past: [],
    future: [],
    pendingKey: null,
    lastKey: null,
  });

beforeEach(resetStore);
afterEach(() => {
  cleanup();
});

describe("useScopeHistoryStore", () => {
  it("arranca con las dos pilas vacías y sin ámbito observado", () => {
    const state = useScopeHistoryStore.getState();
    expect(state.past).toEqual([]);
    expect(state.future).toEqual([]);
    expect(state.pendingKey).toBeNull();
    expect(state.lastKey).toBeNull();
  });

  it("record apila el ámbito anterior y anota el nuevo", () => {
    const previo = scope({ q: "obras" });
    useScopeHistoryStore.getState().record(previo, "q=grúas");
    const state = useScopeHistoryStore.getState();
    expect(state.past).toEqual([previo]);
    expect(state.lastKey).toBe("q=grúas");
  });

  it("record descarta el futuro: rehacer tras una rama nueva mentiría", () => {
    useScopeHistoryStore.setState({ future: [scope({ q: "descartado" })] });
    useScopeHistoryStore.getState().record(scope({ q: "a" }), "q=b");
    expect(useScopeHistoryStore.getState().future).toEqual([]);
  });

  it("record recorta la pila a 40 entradas", () => {
    const store = useScopeHistoryStore.getState();
    for (let i = 0; i < 45; i += 1) {
      store.record(scope({ q: `paso-${i}` }), `q=paso-${i + 1}`);
    }
    const { past } = useScopeHistoryStore.getState();
    expect(past).toHaveLength(40);
    // Se tiran las más antiguas, no las recientes.
    expect(past[0].q).toBe("paso-5");
    expect(past[39].q).toBe("paso-44");
  });

  it("markPending y seed manejan la marca del propio historial", () => {
    useScopeHistoryStore.getState().markPending("q=x");
    expect(useScopeHistoryStore.getState().pendingKey).toBe("q=x");
    useScopeHistoryStore.getState().seed("q=y");
    expect(useScopeHistoryStore.getState().lastKey).toBe("q=y");
    expect(useScopeHistoryStore.getState().pendingKey).toBeNull();
  });

  it("pushUndo devuelve null con la pila vacía y no toca el estado", () => {
    const actual = scope({ q: "actual" });
    expect(useScopeHistoryStore.getState().pushUndo(actual)).toBeNull();
    expect(useScopeHistoryStore.getState().future).toEqual([]);
  });

  it("pushUndo saca la última entrada y manda la actual al futuro", () => {
    const anterior = scope({ q: "anterior" });
    const actual = scope({ q: "actual" });
    useScopeHistoryStore.setState({ past: [anterior] });

    const target = useScopeHistoryStore.getState().pushUndo(actual);

    expect(target).toEqual(anterior);
    const state = useScopeHistoryStore.getState();
    expect(state.past).toEqual([]);
    expect(state.future).toEqual([actual]);
    // Se marca el destino para que el observador no lo re-apile.
    expect(state.pendingKey).toBe(scopeKey(anterior));
    expect(state.lastKey).toBe(scopeKey(anterior));
  });

  it("pushRedo devuelve null con el futuro vacío", () => {
    expect(useScopeHistoryStore.getState().pushRedo(scope())).toBeNull();
  });

  it("pushRedo recupera la primera del futuro y devuelve la actual al pasado", () => {
    const futuro = scope({ q: "futuro" });
    const actual = scope({ q: "actual" });
    useScopeHistoryStore.setState({ future: [futuro] });

    const target = useScopeHistoryStore.getState().pushRedo(actual);

    expect(target).toEqual(futuro);
    const state = useScopeHistoryStore.getState();
    expect(state.future).toEqual([]);
    expect(state.past).toEqual([actual]);
    expect(state.pendingKey).toBe(scopeKey(futuro));
  });

  it("deshacer y rehacer se cancelan: se vuelve al ámbito de partida", () => {
    const a = scope({ q: "a" });
    const b = scope({ q: "b" });
    useScopeHistoryStore.setState({ past: [a] });

    const deshecho = useScopeHistoryStore.getState().pushUndo(b);
    expect(deshecho).toEqual(a);
    const rehecho = useScopeHistoryStore.getState().pushRedo(a);
    expect(rehecho).toEqual(b);
    expect(useScopeHistoryStore.getState().past).toEqual([a]);
    expect(useScopeHistoryStore.getState().future).toEqual([]);
  });

  it("clear vacía las dos pilas y la marca", () => {
    useScopeHistoryStore.setState({
      past: [scope({ q: "a" })],
      future: [scope({ q: "b" })],
      pendingKey: "q=a",
    });
    useScopeHistoryStore.getState().clear();
    const state = useScopeHistoryStore.getState();
    expect(state.past).toEqual([]);
    expect(state.future).toEqual([]);
    expect(state.pendingKey).toBeNull();
  });
});

describe("useScopeHistory", () => {
  const render = (searchParams = "") =>
    renderHook(() => useScopeHistory(), {
      wrapper: withNuqsTestingAdapter({ searchParams }),
    });

  it("siembra el primer ámbito sin apilarlo", () => {
    // Un deep-link compartido no debe traer un "deshacer" que lo vacíe.
    const { result } = render("?q=obras");
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
    expect(useScopeHistoryStore.getState().past).toEqual([]);
    expect(useScopeHistoryStore.getState().lastKey).not.toBeNull();
  });

  it("deshacer y rehacer no hacen nada con la pila vacía", () => {
    const { result } = render("?q=obras");
    act(() => result.current.undo());
    act(() => result.current.redo());
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });

  it("refleja en canUndo/canRedo lo que hay en las pilas", () => {
    const { result, rerender } = render("?q=obras");
    act(() => {
      useScopeHistoryStore.setState({ past: [scope({ q: "previo" })] });
    });
    rerender();
    expect(result.current.canUndo).toBe(true);

    act(() => {
      useScopeHistoryStore.setState({ future: [scope({ q: "siguiente" })] });
    });
    rerender();
    expect(result.current.canRedo).toBe(true);
  });

  it("apila el cambio de ámbito venga de donde venga y lo devuelve al deshacer", async () => {
    // El observador mira el ámbito, así que este cambio entra en la pila igual
    // que si lo hubiera hecho un chip de la barra.
    const { result } = render("?q=obras");
    expect(result.current.canUndo).toBe(false);

    act(() => {
      useScopeHistoryStore.getState().record(scope({ q: "obras" }), "cambio-externo");
    });
    expect(useScopeHistoryStore.getState().past).toHaveLength(1);

    act(() => result.current.undo());

    // Deshacer consume la entrada y deja el ámbito anterior listo para rehacer.
    expect(useScopeHistoryStore.getState().past).toHaveLength(0);
    expect(useScopeHistoryStore.getState().future).toHaveLength(1);
  });

  it("deshacer restaura el ámbito anterior de una sola escritura de URL", async () => {
    // De una sola escritura y no diez: `applySnapshot` manda los diez
    // parámetros juntos, si no cada deshacer costaría diez refetch en cascada.
    const onUrlUpdate = vi.fn();
    const { result } = renderHook(() => useScopeHistory(), {
      wrapper: withNuqsTestingAdapter({ searchParams: "?q=obras", onUrlUpdate }),
    });

    act(() => {
      useScopeHistoryStore.getState().record(scope({ q: "previo" }), useScopeHistoryStore.getState().lastKey!);
    });

    await act(async () => {
      result.current.undo();
    });

    await waitFor(() => expect(onUrlUpdate).toHaveBeenCalledTimes(1));
    expect(onUrlUpdate.mock.calls[0][0].searchParams.get("q")).toBe("previo");
    // La entrada sale del pasado y queda disponible para rehacer.
    expect(useScopeHistoryStore.getState().past).toHaveLength(0);
    expect(useScopeHistoryStore.getState().future).toHaveLength(1);
    expect(useScopeHistoryStore.getState().pendingKey).toBe(scopeKey(scope({ q: "previo" })));
  });

  it("rehacer vuelve a aplicar el ámbito que deshacer apartó", async () => {
    const onUrlUpdate = vi.fn();
    useScopeHistoryStore.setState({ future: [scope({ q: "rehecho" })] });
    const { result } = renderHook(() => useScopeHistory(), {
      wrapper: withNuqsTestingAdapter({ searchParams: "?q=obras", onUrlUpdate }),
    });

    await act(async () => {
      result.current.redo();
    });

    await waitFor(() => expect(onUrlUpdate).toHaveBeenCalledTimes(1));
    expect(onUrlUpdate.mock.calls[0][0].searchParams.get("q")).toBe("rehecho");
    expect(useScopeHistoryStore.getState().future).toHaveLength(0);
  });

  describe("la búsqueda tecleada", () => {
    /**
     * El historial observa la URL, así que apila lo que llega a ella. La
     * búsqueda de la barra escribía en cada tecla: «sap» eran tres entradas de
     * deshacer. Con la espera de la barra (`useValorDiferido`) llega sólo el
     * valor aplicado.
     *
     * Espera corta y relojes reales a propósito. Los 300 ms ya los fijan
     * `use-valor-diferido.test.ts` y el test de la barra; aquí importa cuántas
     * entradas se apilan. La cola con la que nuqs escribe la URL es global:
     * cada test espera a que su última escritura llegue a la URL, porque un
     * vaciado pendiente caería sobre los hooks del test siguiente.
     */
    const ESPERA_MS = 40;
    const montar = (conEspera: boolean) => {
      const alEscribirUrl = vi.fn();
      const hook = renderHook(
        () => {
          const filters = useFilters();
          const historial = useScopeHistory();
          const busqueda = useValorDiferido(filters.q, filters.setQ, ESPERA_MS);
          return { filters, historial, escribir: conEspera ? busqueda.cambiar : filters.setQ };
        },
        // Con memoria: sin ella el adaptador de pruebas vuelve a la URL inicial
        // en cuanto nuqs vacía su cola, y el ámbito olvida lo escrito.
        { wrapper: withNuqsTestingAdapter({ searchParams: "", hasMemory: true, onUrlUpdate: alEscribirUrl }) },
      );
      /** Espera a que `q` haya llegado a la URL, no sólo al estado. */
      const enLaUrl = (q: string) =>
        waitFor(() => expect(alEscribirUrl.mock.calls.at(-1)?.[0].searchParams.get("q")).toBe(q));
      return { ...hook, enLaUrl };
    };

    /**
     * Con cuerpo de bloque a propósito: el `setQ` de nuqs devuelve una promesa,
     * y un `act` que la recibe se trata como asíncrono sin `await`, lo que deja
     * el entorno de `act` roto para el resto del fichero.
     */
    const teclear = (escribir: (valor: string) => void, valor: string) =>
      act(() => {
        escribir(valor);
      });

    it("con la espera, «sap» tecleado de corrido es una sola entrada", async () => {
      const { result, enLaUrl } = montar(true);

      teclear(result.current.escribir, "s");
      teclear(result.current.escribir, "sa");
      teclear(result.current.escribir, "sap");
      await enLaUrl("sap");

      expect(result.current.filters.q).toBe("sap");
      expect(useScopeHistoryStore.getState().past).toHaveLength(1);
      // Deshacer vuelve al ámbito de antes de buscar, no a «sa».
      expect(useScopeHistoryStore.getState().past[0].q).toBe("");
    });

    it("sin ella, cada tecla era una entrada (el comportamiento que se corrige)", async () => {
      const { result, enLaUrl } = montar(false);

      for (const valor of ["s", "sa", "sap"]) {
        teclear(result.current.escribir, valor);
        await enLaUrl(valor);
      }

      expect(useScopeHistoryStore.getState().past.map((entrada) => entrada.q)).toEqual(["", "s", "sa"]);
    });
  });

  it("no re-apila el cambio que provocó el propio historial", () => {
    // Sin la marca `pendingKey`, el ámbito que escribe `undo` volvería a entrar
    // en la pila por la puerta del observador y deshacer/rehacer no avanzaría
    // nunca. Se monta ya con la marca puesta, que es el estado en que queda la
    // app justo después de deshacer.
    const restaurado = scope({ q: "previo" });
    useScopeHistoryStore.setState({
      past: [scope({ q: "anterior" })],
      pendingKey: scopeKey(restaurado),
      lastKey: "un-ambito-distinto",
    });

    render("?q=previo");

    // La marca se consume y la pila se queda como estaba: ni una entrada más.
    expect(useScopeHistoryStore.getState().pendingKey).toBeNull();
    expect(useScopeHistoryStore.getState().lastKey).toBe(scopeKey(restaurado));
    expect(useScopeHistoryStore.getState().past).toHaveLength(1);
  });
});
