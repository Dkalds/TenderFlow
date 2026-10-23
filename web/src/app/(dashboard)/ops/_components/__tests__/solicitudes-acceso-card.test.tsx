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
import type { OpcionesSolicitudesAcceso } from "@/app/(dashboard)/ops/_hooks/use-solicitudes-acceso";
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

interface ConcesionFalsa {
  id: number;
  kind: "email" | "domain";
  value: string;
  active: boolean;
  granted_by: number | null;
  granted_by_nombre: string | null;
  created_at: string;
  updated_at: string;
  revoked_at: string | null;
}

/** Las concesiones que devuelve `/grants`; el backend de mentira no filtra: eso lo pide la URL. */
const concesiones: ConcesionFalsa[] = [];

function concesion(id: number, value: string, extra: Partial<ConcesionFalsa> = {}): ConcesionFalsa {
  return {
    id,
    kind: value.includes("@") ? "email" : "domain",
    value,
    active: true,
    granted_by: 1,
    granted_by_nombre: "Ana Admin",
    created_at: "2026-10-03T10:12:00Z",
    updated_at: "2026-10-03T10:12:00Z",
    revoked_at: null,
    ...extra,
  };
}

/** Defecto del endpoint cuando no se pasa `limit` (`Query(100, ge=1, le=500)`). */
const LIMITE_POR_DEFECTO = 100;

function instalarFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      urlsPedidas.push(url);
      if (url.includes("/grants")) {
        return { ok: true, status: 200, json: async () => concesiones };
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

function renderCard(opciones: OpcionesSolicitudesAcceso = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <SolicitudesAccesoCard {...opciones} />
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
    concesiones.length = 0;
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
    // Con un tope de 3 y no con el de verdad. Llegar a 500 obligaba a pintar
    // 500 filas completas en jsdom, y con la suite entera en paralelo el caso
    // pasaba de los 5 s del timeout (5188 ms el 2026-09-26; aislado, ~400 ms).
    // Lo que se fija no depende del número: el backend de mentira recorta con
    // el `limit` de la URL, así que la tarjeta que pida un tope y cuente con
    // otro, o que vuelva a dar la cifra redonda, pone esto en rojo. Que el
    // tope de verdad es 500 lo fija el test siguiente.
    cola.push(...Array.from({ length: 5 }, (_, i) => solicitud(i + 1, "pendiente")));
    renderCard({ limite: 3 });

    expect(await screen.findByText("3+ pendientes")).toBeInTheDocument();
    expect(screen.getByText(/Se muestran las 3 más recientes/)).toBeInTheDocument();
  });

  it("pide el máximo que admite el endpoint, y no su defecto de 100", async () => {
    // Sin `limit`, el servidor cortaría en 100 y la tarjeta, que compara con
    // su propio tope, daría «100 pendientes» como si fueran todas.
    cola.push(solicitud(1, "pendiente"), solicitud(2, "atendida"));
    renderCard();
    await screen.findByText("alguien-1@empresa.es");
    fireEvent.click(screen.getByRole("button", { name: "Todas" }));
    await screen.findByText("alguien-2@empresa.es");

    // 500 es el `le=500` del endpoint: por encima responde 422.
    const limiteDe = (url: string | undefined) =>
      new URLSearchParams(url?.split("?")[1] ?? "").get("limit");
    expect(limiteDe(queryDe("pendiente"))).toBe("500");
    expect(limiteDe(queryDe("historico"))).toBe("500");
  });

  it("sin pendientes no dice «no ha llegado ninguna solicitud»", async () => {
    // Son dos cosas distintas y el operador actúa distinto ante cada una: la
    // cola vacía se resuelve mirando, el buzón vacío no se resuelve mirando.
    cola.push(solicitud(2, "atendida"));
    renderCard();

    expect(await screen.findByText(/No queda ninguna solicitud pendiente/)).toBeInTheDocument();
  });

  it("conceder el dominio pide confirmación nombrándolo, y solo entonces concede", async () => {
    cola.push(solicitud(1, "pendiente"));
    renderCard();
    await screen.findByText("alguien-1@empresa.es");

    fireEvent.click(screen.getByRole("button", { name: "Conceder dominio" }));

    // La confirmación dice a quién afecta —el dominio entero— y nada sale aún.
    const confirmacion = screen.getByRole("group", { name: /conceder el dominio empresa\.es/ });
    expect(within(confirmacion).getByText(/cualquiera con una cuenta de/)).toBeInTheDocument();
    expect(mutar).not.toHaveBeenCalled();

    fireEvent.click(within(confirmacion).getByRole("button", { name: "Sí, conceder empresa.es" }));

    await waitFor(() => expect(mutar).toHaveBeenCalledTimes(1));
    expect(mutar).toHaveBeenCalledWith(
      "PATCH",
      "/api/v1/admin/solicitudes-acceso/1",
      expect.objectContaining({ estado: "atendida", conceder: "domain", notificar: true }),
    );
  });

  it("cancelar la confirmación del dominio no concede nada", async () => {
    cola.push(solicitud(1, "pendiente"));
    renderCard();
    await screen.findByText("alguien-1@empresa.es");

    fireEvent.click(screen.getByRole("button", { name: "Conceder dominio" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(screen.queryByRole("group", { name: /conceder el dominio/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Conceder dominio" })).toBeInTheDocument();
    expect(mutar).not.toHaveBeenCalled();
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

  // ── Accesos dinámicos: quién concedió, las revocadas y volver a conceder ──

  it("pide las concesiones con las revocadas y dice quién concedió cada una", async () => {
    concesiones.push(
      concesion(11, "ana@empresa.es"),
      concesion(12, "empresa.es", { granted_by: null, granted_by_nombre: null }),
    );
    renderCard();

    expect(await screen.findByText("ana@empresa.es")).toBeInTheDocument();
    // La URL es la que trae las revocadas: sin `include_inactive` el servidor
    // las esconde y no habría nada que volver a conceder.
    expect(urlsPedidas.find((url) => url.includes("/grants"))).toContain("include_inactive=true");
    expect(screen.getByText(/Concedido por Ana Admin el/)).toBeInTheDocument();
    // La del bootstrap no tiene autor y no se le inventa uno.
    expect(screen.getByText(/^Concedido el/)).toBeInTheDocument();
    expect(screen.queryByText(/Revocadas \(/)).not.toBeInTheDocument();
  });

  it("revocar pide confirmación nombrando a quién afecta, y solo entonces revoca", async () => {
    concesiones.push(concesion(12, "empresa.es"));
    renderCard();
    await screen.findByText("empresa.es");

    fireEvent.click(screen.getByRole("button", { name: "Revocar acceso de empresa.es" }));

    const confirmacion = screen.getByRole("group", { name: /revocar acceso de empresa\.es/ });
    // Un dominio revocado deja fuera a todas sus cuentas: se dice antes de pulsar.
    expect(within(confirmacion).getByText(/todas las cuentas de empresa\.es/)).toBeInTheDocument();
    expect(mutar).not.toHaveBeenCalled();

    fireEvent.click(within(confirmacion).getByRole("button", { name: "Sí, revocar" }));

    await waitFor(() => expect(mutar).toHaveBeenCalledTimes(1));
    expect(mutar).toHaveBeenCalledWith("DELETE", "/api/v1/admin/solicitudes-acceso/grants/12");
  });

  it("las revocadas se ven aparte, con su fecha, y se pueden volver a conceder", async () => {
    concesiones.push(
      concesion(11, "ana@empresa.es"),
      concesion(13, "bea@empresa.es", { active: false, revoked_at: "2026-10-05T09:00:00Z" }),
    );
    renderCard();
    await screen.findByText("ana@empresa.es");

    // Plegadas por defecto: lo vivo es lo que se trabaja.
    expect(screen.queryByText("bea@empresa.es")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Revocadas (1)" }));

    expect(await screen.findByText("bea@empresa.es")).toBeInTheDocument();
    expect(screen.getByText(/Revocado el/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Volver a conceder acceso de bea@empresa.es" }));
    const confirmacion = screen.getByRole("group", { name: /volver a conceder acceso de bea@empresa\.es/ });
    expect(mutar).not.toHaveBeenCalled();

    fireEvent.click(within(confirmacion).getByRole("button", { name: "Sí, volver a conceder" }));

    await waitFor(() => expect(mutar).toHaveBeenCalledTimes(1));
    expect(mutar).toHaveBeenCalledWith("POST", "/api/v1/admin/solicitudes-acceso/grants/13/reactivar");
  });
});
