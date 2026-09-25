/**
 * El campo con espera de `hooks/use-valor-diferido.ts`, que es lo que separa
 * la búsqueda del ámbito de la URL.
 *
 * Lo que se fija: la URL recibe el valor cuando se deja de teclear (300 ms en
 * la barra) o en el acto con Enter; un cambio que llega de fuera manda sobre
 * lo tecleado; y el eco de un valor propio no pisa lo que se sigue escribiendo.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useValorDiferido } from "@/hooks/use-valor-diferido";

const RETRASO = 300;

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function montar(inicial = "") {
  const aplicar = vi.fn();
  const hook = renderHook(({ externo }: { externo: string }) => useValorDiferido(externo, aplicar, RETRASO), {
    initialProps: { externo: inicial },
  });
  return { aplicar, ...hook };
}

describe("useValorDiferido", () => {
  it("aplica una sola vez, 300 ms después de la última tecla", () => {
    const { result, aplicar } = montar();

    act(() => result.current.cambiar("s"));
    act(() => vi.advanceTimersByTime(200));
    act(() => result.current.cambiar("sa"));
    act(() => vi.advanceTimersByTime(200));
    act(() => result.current.cambiar("sap"));

    // El campo enseña lo tecleado desde la primera tecla…
    expect(result.current.valor).toBe("sap");
    // …pero fuera todavía no ha llegado nada: cada tecla reinicia la espera.
    act(() => vi.advanceTimersByTime(RETRASO - 1));
    expect(aplicar).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1));
    expect(aplicar).toHaveBeenCalledTimes(1);
    expect(aplicar).toHaveBeenCalledWith("sap");
  });

  it("Enter aplica en el acto y no deja una segunda aplicación pendiente", () => {
    const { result, aplicar } = montar();

    act(() => result.current.cambiar("obras"));
    act(() => result.current.aplicarYa("obras"));
    expect(aplicar).toHaveBeenCalledTimes(1);
    expect(aplicar).toHaveBeenCalledWith("obras");

    act(() => vi.advanceTimersByTime(RETRASO * 2));
    expect(aplicar).toHaveBeenCalledTimes(1);
  });

  it("no aplica nada si lo tecleado vuelve a ser lo que ya había fuera", () => {
    const { result, aplicar } = montar("sap");

    act(() => result.current.cambiar("sapo"));
    act(() => result.current.cambiar("sap"));
    act(() => vi.advanceTimersByTime(RETRASO));

    expect(aplicar).not.toHaveBeenCalled();
  });

  it("un cambio externo (limpiar, deshacer, un enlace) manda y descarta lo pendiente", () => {
    const { result, aplicar, rerender } = montar("obras");

    act(() => result.current.cambiar("obras de"));
    // Antes de que venza la espera, alguien limpia el ámbito.
    rerender({ externo: "" });
    expect(result.current.valor).toBe("");

    act(() => vi.advanceTimersByTime(RETRASO * 2));
    // Lo que se estaba tecleando no resucita el filtro que se acaba de quitar.
    expect(aplicar).not.toHaveBeenCalled();
  });

  it("el eco de un valor propio no pisa la tecla que llegó después", () => {
    const { result, aplicar, rerender } = montar("");

    act(() => result.current.cambiar("sa"));
    act(() => vi.advanceTimersByTime(RETRASO));
    expect(aplicar).toHaveBeenLastCalledWith("sa");

    // La «p» llega antes de que la URL devuelva «sa».
    act(() => result.current.cambiar("sap"));
    rerender({ externo: "sa" });
    expect(result.current.valor).toBe("sap");

    act(() => vi.advanceTimersByTime(RETRASO));
    expect(aplicar).toHaveBeenLastCalledWith("sap");
    expect(aplicar).toHaveBeenCalledTimes(2);
  });

  it("cambiar la función de aplicar entre renders no reinicia la espera", () => {
    const primera = vi.fn();
    const segunda = vi.fn();
    const { result, rerender } = renderHook(
      // `<string>` explícito: con el literal `""` TypeScript infiere el tipo `""`.
      ({ aplicar }: { aplicar: (valor: string) => void }) => useValorDiferido<string>("", aplicar, RETRASO),
      { initialProps: { aplicar: primera } },
    );

    act(() => result.current.cambiar("sap"));
    act(() => vi.advanceTimersByTime(200));
    rerender({ aplicar: segunda });
    act(() => vi.advanceTimersByTime(100));

    // Aplica a los 300 ms de la tecla, con la función vigente en ese momento.
    expect(primera).not.toHaveBeenCalled();
    expect(segunda).toHaveBeenCalledWith("sap");
  });
});
