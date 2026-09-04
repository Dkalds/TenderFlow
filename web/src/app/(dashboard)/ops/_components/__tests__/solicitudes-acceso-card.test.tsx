import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * Lo que se fija aquí es que **ninguna solicitud pendiente pueda caerse de la
 * pantalla**.
 *
 * El endpoint devuelve las N más recientes por `created_at DESC` mezclando los
 * tres estados. Pedirlo sin filtro hacía que, con la cola histórica por encima
 * de la ventana, una pendiente antigua desapareciera sin ruta para volver a
 * ella; y el contador de la cabecera, calculado sobre esa misma ventana,
 * confirmaba tranquilamente que no quedaba nada por atender. En un producto de
 * acceso por invitación eso es una persona que escribió y a la que nadie
 * contestó, así que los tests miran la **query que sale** y no sólo lo que se
 * pinta: filtrar en cliente pasaría igual de verde y volvería a perder filas.
 */

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

// El factory sustituye el MÓDULO ENTERO, así que tiene que exponer todo lo que
// el componente importe de él: cuando la tarjeta pasó de `fetch` crudo a
// `fetchWithAuth` (migración al cliente tipado, 2026-09), este mock seguía
// devolviendo sólo `apiMutate` y el componente recibía `undefined`. Resultado:
// las tres queries fallaban, la tarjeta se pintaba vacía y los siete tests
// morían con «Unable to find an element with the text».
//
// `fetchWithAuth` delega en el `fetch` stubbeado en vez de devolver datos por su
// cuenta, y eso es deliberado: lo que estos tests vigilan es **la query que
// sale** (`urlsPedidas`), no lo que se pinta. Un mock que se saltara `fetch`
// dejaría de registrar la URL y el test pasaría a verde sin comprobar nada —
// justo el fallo que documenta la cabecera de este fichero.
vi.mock("@/lib/api-client", () => ({
  apiMutate: vi.fn(),
  fetchWithAuth: vi.fn(async (url: string) => {
    const respuesta = (await (globalThis.fetch as unknown as (u: string) => Promise<unknown>)(
      url,
    )) as { json: () => Promise<unknown> };
    return respuesta.json();
  }),
}));

import { SolicitudesAccesoCard } from "@/app/(dashboard)/ops/_components/solicitudes-acceso-card";
import { apiMutate } from "@/lib/api-client";

const mutar = vi.mocked(apiMutate);

interface SolicitudFalsa {
  id: number;
  email: string;
  estado: string;
  created_at: string;
}

function solicitud(id: number, estado: string): SolicitudFalsa {
  return {
    id,
    email: `alguien-${id}@empresa.es`,
    estado,
    created_at: "2026-08-01T00:00:00Z",
  };
}

/**
 * Backend de mentira que **filtra y recorta de verdad**, como el real.
 *
 * Es la mitad del valor de estos tests. Un doble que devolviera siempre la cola
 * entera dejaría pasar tanto al componente que ignora `estado` como al que
 * filtra en cliente, que son justo los dos que pierden solicitudes. `cola` va
 * en el mismo orden que la respuesta real —`created_at DESC`, lo más reciente
 * primero— y el corte se aplica después de filtrar, igual que en SQL.
 */
const cola: SolicitudFalsa[] = [];
let urlsPedidas: string[] = [];

/** Defecto del endpoint cuando no se pasa `limit` (`Query(100, ge=1, le=500)`). */
const LIMITE_POR_DEFECTO = 100;

function instalarFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      urlsPedidas.push(url);
      if (url.includes("/grants")) {
        return { ok: true, status: 200, json: async () => [] };
      }
      const params = new URLSearchParams(url.split("?")[1] ?? "");
      const estado = params.get("estado");
      const limite = Number(params.get("limit") ?? LIMITE_POR_DEFECTO);
      const filtradas = estado ? cola.filter((s) => s.estado === estado) : cola;
      const cuerpo = filtradas.slice(0, limite);
      return { ok: true, status: 200, json: async () => cuerpo };
    }),
  );
}

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <SolicitudesAccesoCard />
    </QueryClientProvider>,
  );
}

function queryDe(vista: "pendiente" | "historico"): string | undefined {
  return urlsPedidas.find(
    (url) =>
      !url.includes("/grants") &&
      (vista === "pendiente" ? url.includes("estado=pendiente") : !url.includes("estado=")),
  );
}

describe("SolicitudesAccesoCard", () => {
  beforeEach(() => {
    cleanup();
    urlsPedidas = [];
    cola.length = 0;
    mutar.mockReset();
    mutar.mockResolvedValue({ status: "ok", notificado: null });
    instalarFetch();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("por defecto pide sólo las pendientes al servidor", async () => {
    cola.push(solicitud(1, "pendiente"), solicitud(2, "atendida"));
    renderCard();

    expect(await screen.findByText("alguien-1@empresa.es")).toBeInTheDocument();
    // El recorte lo tiene que aplicar el servidor: si esta fila se hubiera
    // filtrado aquí, la pendiente antigua ya se habría perdido antes.
    expect(queryDe("pendiente")).toBeTruthy();
    expect(screen.queryByText("alguien-2@empresa.es")).not.toBeInTheDocument();
  });

  it("una pendiente vieja sepultada bajo el histórico sigue saliendo", async () => {
    // La forma exacta del fallo: la pendiente es la MÁS antigua, así que en una
    // ventana por `created_at DESC` sin filtrar cae por debajo del corte.
    cola.push(
      ...Array.from({ length: 120 }, (_, i) => solicitud(100 + i, "atendida")),
      solicitud(1, "pendiente"),
    );
    renderCard();

    expect(await screen.findByText("alguien-1@empresa.es")).toBeInTheDocument();
  });

  it("el histórico es otra consulta, y sólo se pide si se abre", async () => {
    cola.push(solicitud(1, "pendiente"), solicitud(2, "descartada"));
    renderCard();
    await screen.findByText("alguien-1@empresa.es");
    expect(queryDe("historico")).toBeUndefined();

    fireEvent.click(screen.getByRole("button", { name: "Todas" }));

    expect(await screen.findByText("alguien-2@empresa.es")).toBeInTheDocument();
    expect(queryDe("historico")).toBeTruthy();
  });

  it("el contador no se calcula sobre la ventana que se está mirando", async () => {
    cola.push(solicitud(1, "pendiente"), solicitud(2, "pendiente"), solicitud(3, "atendida"));
    renderCard();
    await screen.findByText("alguien-1@empresa.es");
    const cabecera = screen.getByText("Solicitudes de acceso").parentElement as HTMLElement;
    expect(within(cabecera).getByText("2 pendientes")).toBeInTheDocument();

    // En el histórico el contador sigue siendo 2: sale de su propia consulta
    // filtrada, no de contar pendientes dentro de la lista visible.
    fireEvent.click(screen.getByRole("button", { name: "Todas" }));
    await screen.findByText("alguien-3@empresa.es");
    expect(within(cabecera).getByText("2 pendientes")).toBeInTheDocument();
  });

  it("cuando la respuesta llega al tope lo dice, en vez de dar un número redondo", async () => {
    cola.push(...Array.from({ length: 500 }, (_, i) => solicitud(i + 1, "pendiente")));
    renderCard();

    expect(await screen.findByText("500+ pendientes")).toBeInTheDocument();
    expect(screen.getByText(/Se muestran las 500 más recientes/)).toBeInTheDocument();
  });

  it("sin pendientes no dice «no ha llegado ninguna solicitud»", async () => {
    // Son dos cosas distintas y el operador actúa distinto ante cada una: la
    // cola vacía se resuelve mirando, el buzón vacío no se resuelve mirando.
    cola.push(solicitud(2, "atendida"));
    renderCard();

    expect(await screen.findByText(/No queda ninguna solicitud pendiente/)).toBeInTheDocument();
  });

  it("conceder una solicitud activa el email antes de avisar", async () => {
    cola.push(solicitud(1, "pendiente"));
    renderCard();
    await screen.findByText("alguien-1@empresa.es");
    const pedidasAntes = urlsPedidas.length;

    fireEvent.click(screen.getByRole("button", { name: "Conceder email y avisar" }));

    // La clave de las dos consultas comparte prefijo, así que el
    // `invalidateQueries` del `onSuccess` alcanza a ambas: el contador no puede
    // quedarse contando una pendiente que acaba de dejar de serlo.
    await waitFor(() => expect(urlsPedidas.length).toBeGreaterThan(pedidasAntes));
    expect(mutar).toHaveBeenCalledWith(
      "PATCH",
      "/api/v1/admin/solicitudes-acceso/1",
      expect.objectContaining({
        estado: "atendida",
        conceder: "email",
        notificar: true,
      }),
    );
  });
});
