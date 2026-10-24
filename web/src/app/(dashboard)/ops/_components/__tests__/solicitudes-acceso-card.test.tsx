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
let concesiones: Record<string, unknown>[] = [];

/** Defecto del endpoint cuando no se pasa `limit` (`Query(100, ge=1, le=500)`). */
const LIMITE_POR_DEFECTO = 100;

function instalarFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      urlsPedidas.push(url);
      if (url.includes("/grants")) {
        // Como el endpoint: sin `include_inactive` solo las vivas.
        const todas = new URLSearchParams(url.split("?")[1] ?? "").get("include_inactive") === "true";
        const cuerpo = todas ? concesiones : concesiones.filter((g) => g.active);
        return { ok: true, status: 200, json: async () => cuerpo };
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
    concesiones = [];
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

  describe("accesos concedidos", () => {
    const viva = {
      id: 1,
      kind: "email",
      value: "alguien-1@empresa.es",
      active: true,
      granted_by: 7,
      granted_by_name: "Admin Uno",
      created_at: "2026-08-01T10:00:00Z",
      updated_at: "2026-08-02T10:00:00Z",
      revoked_at: null,
    };
    const revocada = {
      id: 2,
      kind: "email",
      value: "alguien-2@empresa.es",
      active: false,
      granted_by: null,
      granted_by_name: null,
      created_at: "2026-07-01T10:00:00Z",
      updated_at: "2026-07-05T10:00:00Z",
      revoked_at: "2026-07-05T10:00:00Z",
    };

    it("pide también las revocadas y dice quién concedió cada una", async () => {
      concesiones.push(viva, revocada);
      renderCard();

      expect(await screen.findByText(/Concedido por Admin Uno el /)).toBeInTheDocument();
      expect(urlsPedidas.some((u) => u.includes("/grants?include_inactive=true"))).toBe(true);
      // Sin autor registrado no se inventa uno.
      expect(screen.getByText(/Concedido por autor no registrado · revocado el /)).toBeInTheDocument();
    });

    it("lista las revocadas aparte y no les ofrece «Revocar»", async () => {
      concesiones.push(viva, revocada);
      renderCard();

      await screen.findByText("Accesos revocados");
      expect(screen.getByRole("button", { name: "Revocar acceso de alguien-1@empresa.es" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Revocar acceso de alguien-2@empresa.es" })).toBeNull();
    });

    it("vuelve a conceder una revocada con el PATCH de su solicitud", async () => {
      concesiones.push(revocada);
      // La solicitud de esa persona, ya atendida, solo está en el histórico.
      cola.push(solicitud(2, "atendida"));
      renderCard();

      const boton = await screen.findByRole("button", {
        name: "Volver a conceder acceso a alguien-2@empresa.es",
      });
      await waitFor(() => expect(boton).toBeEnabled());
      fireEvent.click(boton);

      await waitFor(() =>
        expect(mutar).toHaveBeenCalledWith(
          "PATCH",
          "/api/v1/admin/solicitudes-acceso/2",
          expect.objectContaining({ estado: "atendida", conceder: "email" }),
        ),
      );
    });

    it("una revocada de dominio se vuelve a conceder sobre una solicitud de ese dominio", async () => {
      concesiones.push({ ...revocada, id: 3, kind: "domain", value: "empresa.es" });
      cola.push(solicitud(9, "descartada"));
      renderCard();

      const boton = await screen.findByRole("button", {
        name: "Volver a conceder acceso a empresa.es",
      });
      await waitFor(() => expect(boton).toBeEnabled());
      fireEvent.click(boton);

      await waitFor(() =>
        expect(mutar).toHaveBeenCalledWith(
          "PATCH",
          "/api/v1/admin/solicitudes-acceso/9",
          expect.objectContaining({ conceder: "domain" }),
        ),
      );
    });

    it("sin solicitud que case no deja conceder y lo explica", async () => {
      concesiones.push(revocada);
      renderCard();

      const boton = await screen.findByRole("button", {
        name: "Volver a conceder acceso a alguien-2@empresa.es",
      });
      expect(boton).toBeDisabled();
      expect(await screen.findByText(/No hay ninguna solicitud con ese correo/)).toBeInTheDocument();
      expect(mutar).not.toHaveBeenCalled();
    });
  });
});
