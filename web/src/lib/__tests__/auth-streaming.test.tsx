/**
 * La sesión no puede tirar el HTML de un límite de Suspense que aún no se ha
 * revelado.
 *
 * El HTML de una pantalla con prefetch en servidor (`resumen/page.tsx`) llega
 * en dos tiempos: el marco con el esqueleto de `loading.tsx` y, cuando acaba
 * el prefetch, el cuerpo de la vista en un `<div hidden id="S:n">` más un
 * `$RC(...)`. Desde React 19.2 `$RC` no revela en el acto: marca el límite
 * como `$~` (en cola) y el `$RV` que lo revela espera al siguiente frame, o a
 * que pasen 300 ms desde la revelación anterior. Mientras tanto React hidrata
 * el resto y `/auth/me` responde.
 *
 * `SessionProvider` metía la sesión en el valor del contexto. Ese cambio de
 * valor alcanza al límite deshidratado; React no puede hidratar un límite en
 * cola, así que descartaba su HTML y lo pintaba de nuevo en el cliente. El
 * `<div hidden id="S:n">` con la copia del servidor seguía en el DOM hasta que
 * corría `$RV` —con la pestaña en segundo plano, no hasta volver a ella—, y el
 * DOM tenía la pantalla dos veces: IDs duplicados (`e2e/accessibility.spec.ts`
 * en /resumen, a ratos) y el render del servidor tirado.
 *
 * Aquí se reproduce con el Fizz de verdad: el HTML sale de
 * `renderToReadableStream`, las instrucciones que emite (`$RC`) se ejecutan
 * sobre el DOM y el `requestAnimationFrame` del que cuelga `$RV` se retiene
 * para abrir la ventana en la que llega la sesión.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import * as React from "react";
import { act } from "react";
import { hydrateRoot } from "react-dom/client";
import { screen, waitFor } from "@testing-library/react";
import { renderToReadableStream } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider, useSession } from "@/lib/auth";

type Leible<T> = Promise<T> & { status?: "fulfilled"; value?: T };

/** Una promesa que `use` lee sin suspender: el dato ya está en el cliente. */
function yaResuelta<T>(valor: T): Leible<T> {
  const promesa: Leible<T> = Promise.resolve(valor);
  promesa.status = "fulfilled";
  promesa.value = valor;
  return promesa;
}

/** La vista que llega tarde: lee su dato y la sesión, y lleva un id. */
function Vista({ dato }: { dato: Promise<string> }) {
  const texto = React.use(dato);
  const { user, isLoading } = useSession();
  return (
    <section id="vista">
      {texto}: {isLoading ? "comprobando sesión" : (user?.email ?? "sin sesión")}
    </section>
  );
}

/** Fuera del límite, como el menú de cuenta del rail: se hidrata en el acto. */
function Cuenta() {
  const { user, isLoading } = useSession();
  return <span data-testid="cuenta">{isLoading ? "…" : (user?.email ?? "anónimo")}</span>;
}

function Pantalla({ cliente, dato }: { cliente: QueryClient; dato: Promise<string> }) {
  return (
    <QueryClientProvider client={cliente}>
      <SessionProvider>
        <Cuenta />
        <main>
          <React.Suspense fallback={<p>cargando</p>}>
            <Vista dato={dato} />
          </React.Suspense>
        </main>
      </SessionProvider>
    </QueryClientProvider>
  );
}

function clienteNuevo() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

/**
 * HTML de la pantalla en dos tiempos: el marco se lee antes de que el dato de
 * la vista exista, así que el límite sale pendiente y su contenido llega
 * después, en un segmento oculto con su `$RC`.
 */
async function htmlEnStreaming(): Promise<string> {
  let soltar!: (valor: string) => void;
  const dato = new Promise<string>((resolver) => {
    soltar = resolver;
  });
  const flujo = await renderToReadableStream(<Pantalla cliente={clienteNuevo()} dato={dato} />);
  const lector = flujo.getReader();
  const decodificador = new TextDecoder();
  let html = "";
  const primero = await lector.read();
  html += decodificador.decode(primero.value);
  soltar("datos del ámbito");
  for (;;) {
    const { done, value } = await lector.read();
    if (done) break;
    html += decodificador.decode(value);
  }
  return html;
}

function idsDuplicados(): string[] {
  const vistos = new Map<string, number>();
  for (const elemento of document.querySelectorAll("[id]")) {
    vistos.set(elemento.id, (vistos.get(elemento.id) ?? 0) + 1);
  }
  return [...vistos].filter(([, veces]) => veces > 1).map(([id]) => id);
}

function segmentosOcultos(): string[] {
  return [...document.querySelectorAll('div[hidden][id^="S:"]')].map((segmento) => segmento.id);
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("SessionProvider y el HTML en streaming", () => {
  it("la sesión que llega antes de revelar un límite no descarta su HTML ni lo duplica", async () => {
    const html = await htmlEnStreaming();
    // Lo que se prueba sólo existe si el límite salió pendiente y su contenido
    // llegó aparte: si React cambiara el formato, el test lo diría aquí.
    expect(html).toContain('<template id="B:0">');
    expect(html).toContain('<div hidden id="S:0">');
    expect(html).toContain('$RC("B:0","S:0")');

    // Los frames se retienen —el que marca el primer pintado y el del que
    // cuelga la revelación (`$RV`)—: es la ventana en la que llegan la
    // hidratación y `/auth/me`.
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", (llamada: FrameRequestCallback) => {
      frames.push(llamada);
      return frames.length;
    });

    let responder!: () => void;
    const respuesta = new Promise<Response>((resolver) => {
      responder = () =>
        resolver(
          new Response(JSON.stringify({ user_id: "u1", email: "ana@example.test", display_name: "Ana", is_admin: false }), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
        );
    });
    vi.stubGlobal("fetch", vi.fn(() => respuesta));

    const raiz = document.createElement("div");
    raiz.innerHTML = html;
    document.body.appendChild(raiz);
    // `innerHTML` no ejecuta scripts; el navegador sí los ejecuta según llegan.
    for (const script of raiz.querySelectorAll("script")) {
      new Function(script.textContent ?? "")();
      script.remove();
    }
    // `$RC` ya ha pasado: el límite está en cola (`$~`) y su contenido, oculto
    // aparte, a la espera del frame de `$RV`.
    expect((document.getElementById("B:0")?.previousSibling as Comment | null)?.data).toBe("$~");
    expect(segmentosOcultos()).toEqual(["S:0"]);
    const vistaDelServidor = document.getElementById("vista");
    expect(vistaDelServidor?.textContent).toBe("datos del ámbito: comprobando sesión");

    // Servidor y cliente comparten proceso y objetos de contexto, y los dos
    // renderers de React se declaran primarios: React avisa de «multiple
    // renderers» en cuanto el cliente usa un contexto que tocó el servidor.
    // Es un artefacto del test; cualquier otro error de consola sí cuenta.
    const errores = vi.spyOn(console, "error").mockImplementation(() => {});
    const erroresRecuperables = vi.fn();
    let hidratada: ReturnType<typeof hydrateRoot> | undefined;
    await act(async () => {
      hidratada = hydrateRoot(raiz, <Pantalla cliente={clienteNuevo()} dato={yaResuelta("datos del ámbito")} />, {
        onRecoverableError: erroresRecuperables,
      });
    });
    expect(screen.getByTestId("cuenta")).toHaveTextContent("…");

    // Llega la sesión con el límite todavía sin revelar, y lo de fuera ya la
    // pinta.
    responder();
    await waitFor(() => expect(screen.getByTestId("cuenta")).toHaveTextContent("ana@example.test"));

    // Nada se ha pintado dos veces: el límite sigue esperando su revelación
    // con el HTML del servidor, en vez de haberse repintado en el cliente al
    // lado de la copia oculta.
    expect(idsDuplicados()).toEqual([]);
    expect(document.getElementById("B:0")).not.toBeNull();

    // Corre `$RV`: mueve el segmento a su sitio y pide a React que hidrate.
    await act(async () => {
      for (let i = 0; i < 5 && frames.length; i++) frames.splice(0).forEach((frame) => frame(performance.now()));
    });

    expect(segmentosOcultos()).toEqual([]);
    expect(idsDuplicados()).toEqual([]);
    expect(erroresRecuperables).not.toHaveBeenCalled();
    // Hidratado, no repintado: es el nodo del servidor, y ya lee la sesión.
    expect(document.getElementById("vista")).toBe(vistaDelServidor);
    expect(vistaDelServidor?.textContent).toBe("datos del ámbito: ana@example.test");

    const otrosErrores = errores.mock.calls
      .map((argumentos) => argumentos.map(String).join(" "))
      .filter((mensaje) => !mensaje.includes("multiple renderers concurrently rendering the same context provider"));
    expect(otrosErrores).toEqual([]);

    await act(async () => {
      hidratada?.unmount();
    });
  });
});
