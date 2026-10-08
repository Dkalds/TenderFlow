import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const fetchWithAuth = vi.hoisted(() => vi.fn((_url: string) => new Promise(() => {})));
vi.mock("@/lib/api-client", () => ({ fetchWithAuth }));

/**
 * El ámbito vive en nuqs; aquí sólo interesa el valor ya resuelto. `useScopedHref`
 * usa la implementación real de `mergeFiltersIntoPath` sobre un ámbito fijo, que
 * es justo lo que se quiere verificar: que el enlace de la tarjeta arrastra los
 * chips activos en vez de descartarlos.
 */
const scope = vi.hoisted(() => ({
  params: {} as Record<string, string>,
  qs: "",
  estados: [] as string[],
  q: "",
  importeMin: null as number | null,
  soloAbiertas: false,
}));

vi.mock("@/lib/filters", async () => {
  const real = await vi.importActual<typeof import("@/lib/filters")>("@/lib/filters");
  return {
    ...real,
    useFilterParams: () => scope.params,
    useFilters: () => ({
      q: scope.q,
      estados: scope.estados,
      importeMin: scope.importeMin,
      soloAbiertas: scope.soloAbiertas,
      ccaas: [],
      tecnologias: [],
      rango: { desde: null, hasta: null },
    }),
    useScopedHref: () => (path: string) => real.mergeFiltersIntoPath(path, scope.qs),
  };
});

import { AtencionCards } from "@/app/(dashboard)/resumen/_components/atencion-cards";

const HOY = {
  calientes: 12,
  vencen_48h: 37,
  nuevas_24h: 8,
  total_activas: 42100,
  importe_p75: 250000,
};

function key(base: string[], url: string) {
  return [...base, url, { ...scope.params }];
}

/** Última visita: el corte con el que cuenta «Nuevas». */
const DESDE = "2026-09-29T08:15:00+00:00";
const NOVEDADES = { count: 8, sample: [], desde: DESDE };

function renderCards(
  hoy: Record<string, unknown> = HOY,
  novedades: Record<string, unknown> | null = NOVEDADES,
) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  qc.setQueryData(key(["analytics", "resumen", "hoy"], "/api/v1/analytics/resumen/hoy"), hoy);
  if (novedades) {
    qc.setQueryData(
      key(["analytics", "resumen", "novedades"], "/api/v1/analytics/resumen/novedades"),
      novedades,
    );
  }
  return render(
    <QueryClientProvider client={qc}>
      <AtencionCards />
    </QueryClientProvider>,
  );
}

function hrefDe(titulo: string): string {
  const link = screen.getByText(titulo).closest("a");
  return link?.getAttribute("href") ?? "";
}

describe("AtencionCards", () => {
  beforeEach(() => {
    cleanup();
    // `mockReset` y no `mockClear`: los tests que resuelven el desglose dejan
    // puesta su implementación, y la siguiente prueba la heredaría.
    fetchWithAuth.mockReset();
    fetchWithAuth.mockImplementation(() => new Promise(() => {}));
    scope.params = {};
    scope.qs = "";
    scope.estados = [];
    scope.q = "";
    scope.importeMin = null;
    scope.soloAbiertas = false;
  });

  it("pinta los tres contadores que exigen acción hoy", () => {
    renderCards();
    expect(screen.getByText("37")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
  });

  it("«Total activas» ya no vive aquí: bajó a la tira de contexto", () => {
    // No exige nada para hoy y ocupaba un cuarto de la banda urgente. Se
    // comprueba por el número para que el test falle si vuelve a colarse.
    renderCards();
    expect(screen.queryByText("42.100")).not.toBeInTheDocument();
    expect(screen.queryByText("Total activas")).not.toBeInTheDocument();
  });

  it("arrastra el ámbito activo a los tres destinos", () => {
    // El bug: la tarjeta contaba dentro del ámbito («4.210 activas en Madrid»)
    // y su enlace abría /detalle sin la CCAA — otro universo, mismo número.
    scope.qs = "?ccaa=Madrid&tecnologia=SAP";
    renderCards();
    for (const titulo of ["Ver la cola de cierre", "Grandes en plazo", "Nuevas"]) {
      expect(hrefDe(titulo)).toContain("ccaa=Madrid");
      expect(hrefDe(titulo)).toContain("tecnologia=SAP");
    }
  });

  it("conserva el recorte propio de la tarjeta junto al ámbito", () => {
    scope.qs = "?ccaa=Madrid";
    renderCards();
    expect(hrefDe("Nuevas")).toContain("fecha_desde=2026-09-29");
    expect(hrefDe("Nuevas")).toContain("ccaa=Madrid");
  });

  it("«Nuevas» cuenta desde tu última visita, no las últimas 24 horas", () => {
    // Eran tres ideas de «nuevo»: «Nuevas 24h», la línea de novedades del
    // mercado entero y la banda de lo que sigues. La tarjeta cuenta ahora el
    // corte de la última visita, dentro del ámbito, y dice cuál es.
    renderCards({ ...HOY, nuevas_24h: 99 });
    expect(screen.queryByText("99")).not.toBeInTheDocument();
    expect(screen.queryByText("Nuevas 24h")).not.toBeInTheDocument();
    expect(screen.getByText(/^Desde tu última visita, el /)).toBeInTheDocument();
    expect(screen.getByText(/^Abre Detalle: publicadas desde el /)).toBeInTheDocument();
  });

  it("si no se puede comprobar la última visita, no inventa la cifra", () => {
    renderCards(HOY, null);
    // Sin dato en caché, la consulta queda pendiente (el doble no resuelve):
    // la tarjeta enseña su esqueleto, no un cero.
    const tarjeta = screen.getByText("Nuevas").closest("a");
    expect(tarjeta?.textContent).not.toMatch(/\b0\b/);
  });

  it("la cola de cierre abre la ventana que cuenta, y lo declara", () => {
    // Era el destino roto del rediseño: contaba 37 y abría las 148.000 del
    // catálogo entero. `GET /licitaciones` ya acota por `fecha_limite`.
    renderCards();
    const href = hrefDe("Ver la cola de cierre");
    expect(href).toMatch(/cierre_desde=\d{4}-\d{2}-\d{2}/);
    expect(href).toMatch(/cierre_hasta=\d{4}-\d{2}-\d{2}/);
    // El contador ya no cuenta las cerradas con plazo en la ventana: el listado
    // que abre tampoco.
    expect(href).toContain("solo_abiertas=true");
    expect(screen.getByText("Abre Detalle: cierran en 48 h")).toBeInTheDocument();
    expect(screen.queryByText(/Aprox\. · Abre Detalle: cierran/)).not.toBeInTheDocument();
  });

  it("«Grandes en plazo» corta por el P75 que publica el endpoint, y en plazo", () => {
    renderCards();
    expect(hrefDe("Grandes en plazo")).toContain("importe_min=250000");
    expect(hrefDe("Grandes en plazo")).toContain("solo_abiertas=true");
    expect(hrefDe("Grandes en plazo")).toMatch(/cierre_desde=\d{4}-\d{2}-\d{2}/);
    expect(
      screen.getByText("Abre Detalle: abiertas en plazo del 25 % de mayor importe"),
    ).toBeInTheDocument();
  });

  it("con ámbito activo sigue siendo exacta: el P75 que llega es el del ámbito", () => {
    // Antes el endpoint no publicaba el P75 con filtros y la tarjeta se
    // declaraba aproximada justo en el caso normal: cualquier chip puesto.
    scope.qs = "?tecnologia=SAP";
    renderCards({ ...HOY, importe_p75: 90000 });
    expect(hrefDe("Grandes en plazo")).toContain("importe_min=90000");
    expect(hrefDe("Grandes en plazo")).toContain("tecnologia=SAP");
    expect(screen.queryByText(/Aprox\./)).not.toBeInTheDocument();
  });

  it("sin P75 —un ámbito sin importes— «Grandes en plazo» se declara aproximada", () => {
    renderCards({ ...HOY, importe_p75: null });
    expect(hrefDe("Grandes en plazo")).not.toContain("importe_min");
    expect(
      screen.getByText(/Aprox\. · Abre Detalle: abiertas en plazo, sin umbral/),
    ).toBeInTheDocument();
  });

  it("sin nada que vencer, la cola se resuelve en verde y no pide el desglose", () => {
    renderCards({ ...HOY, vencen_48h: 0 });
    expect(screen.getByText("Nada vence en las próximas 48 horas")).toBeInTheDocument();
    // La petición del desglose va con `enabled`: sin cola no se lanza.
    const pedidas = fetchWithAuth.mock.calls.map(([url]) => url);
    expect(pedidas.some((url) => url.includes("cierre_desde"))).toBe(false);
  });

  it("con cola, pide el desglose acotado a la ventana de cierre", () => {
    renderCards();
    const pedidas = fetchWithAuth.mock.calls.map(([url]) => url);
    const cola = pedidas.find((url) => url.includes("/api/v1/licitaciones"));
    expect(cola).toBeDefined();
    // Por el cursor, no por el listado por offset que se retira (RFC
    // 2026-09-06); y sin COUNT(*): el recorte lo dice `has_more`.
    expect(cola).toContain("/api/v1/licitaciones/cursor?");
    expect(cola).not.toContain("with_total");
    expect(cola).toMatch(/cierre_desde=\d{4}-\d{2}-\d{2}/);
    expect(cola).toMatch(/cierre_hasta=\d{4}-\d{2}-\d{2}/);
    // `vencen_48h` cuenta con guardia de estado, así que la lista también la
    // pone: sin ella enseñaría anuladas que el número ya no cuenta.
    expect(cola).toContain("solo_abiertas=true");
  });

  it("el desglose aplica el ámbito entero, igual que el contador", () => {
    // El contador ya aplica la barra entera: si la lista recortara el ámbito
    // saldría más ancha que su propio encabezado.
    scope.params = { estado: "PUB", q: "sanidad", ccaa: "Madrid" };
    renderCards();
    const cola = fetchWithAuth.mock.calls
      .map(([url]) => url)
      .find((url) => url.includes("/api/v1/licitaciones"));
    expect(cola).toContain("ccaa=Madrid");
    expect(cola).toContain("estado=PUB");
    expect(cola).toContain("q=sanidad");
  });

  it("desglosa la cola en filas, ordenadas por lo que queda y no por lo que llegó", async () => {
    // El cambio de fondo del rediseño: la tarjeta pasa de decir «37» a decir
    // *cuáles*. El endpoint no ordena por `fecha_limite` —no está entre los
    // valores de `sort`—, así que si esto no ordenase en cliente la tarjeta
    // enseñaría cuatro cualesquiera de la ventana.
    // El medio minuto de holgura no es decorativo: las horas se redondean
    // **hacia abajo** a propósito (un plazo que se agota no regala tiempo), así
    // que un cierre a exactamente +9 h se lee «8 h» en cuanto pasa un
    // milisegundo entre montar el componente y calcular el plazo.
    const enHoras = (h: number) => new Date(Date.now() + h * 3_600_000 + 30_000).toISOString();
    fetchWithAuth.mockImplementation((url: string) =>
      url.includes("/api/v1/licitaciones")
        ? Promise.resolve({
            total: 2,
            items: [
              {
                id_externo: "LEJOS",
                titulo: "Cierra pasado mañana",
                organo_contratacion: "Universidad de Sevilla",
                importe: 740000,
                fecha_limite: enHoras(38),
              },
              {
                id_externo: "PRONTO",
                titulo: "Cierra esta tarde",
                organo_contratacion: "AEAT",
                importe: 4820000,
                fecha_limite: enHoras(9),
              },
            ],
          })
        : new Promise(() => {}),
    );

    renderCards();

    expect(await screen.findByText("Cierra esta tarde")).toBeInTheDocument();
    expect(screen.getAllByText(/^\d+ h$/).map((n) => n.textContent)).toEqual(["9 h", "38 h"]);
    // Cada fila abre su ficha: es lo que ahorra el viaje al listado.
    expect(hrefDe("Cierra esta tarde")).toContain("lic=PRONTO");
    expect(screen.getByText("AEAT")).toBeInTheDocument();
  });

  it("no avisa de filtros ignorados: el endpoint aplica el ámbito entero", () => {
    // Con búsqueda y estado la banda decía «Estas cifras no aplican búsqueda y
    // estado». Ya los aplica, y el aviso no tiene nada que declarar.
    scope.estados = ["PUB"];
    scope.q = "sanidad";
    renderCards();
    expect(screen.queryByText(/no aplican/)).not.toBeInTheDocument();
  });

  it("«Grandes en plazo» dice en cifra dónde empieza el 25 % de mayor importe", () => {
    renderCards();
    expect(screen.getByText(/^Desde .+: el 25 % de mayor importe, abiertas y en plazo$/)).toBeInTheDocument();
  });

  it("«Nuevas» enseña bajo la cifra la muestra que trae el endpoint", () => {
    renderCards(HOY, {
      ...NOVEDADES,
      sample: [
        { id_externo: "N1", titulo: "Servicio de ciberseguridad gestionada", importe: 960000, organo_contratacion: null },
        { id_externo: "N2", titulo: null, importe: null, organo_contratacion: null },
      ],
    });
    const tarjeta = screen.getByText("Nuevas").closest("a");
    expect(tarjeta).toHaveTextContent("Servicio de ciberseguridad gestionada");
    // Sin título, el expediente se nombra por su id y no por «undefined».
    expect(tarjeta).toHaveTextContent("N2");
  });
});
