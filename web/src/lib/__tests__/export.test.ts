/**
 * Tests de `web/src/lib/export.ts`.
 *
 * Lo que se fija aquí, además del armado de la query, son las dos cosas que
 * estaban rotas y no se veían:
 *
 * 1. El Excel se pide con `format=excel`, que es el literal que declara la API
 *    (`api/routes/exports.py`); `xlsx` es sólo la extensión del fichero y
 *    devolvía un 422. La versión anterior de este fichero afirmaba `xlsx` y por
 *    tanto blindaba el bug: un test verde no es lo mismo que un producto que
 *    funciona.
 * 2. Una descarga que falla no puede pasar por descarga. El `<a download>` a
 *    ciegas no distinguía un 422 de un 200, y el evento se emitía antes de
 *    tener respuesta, así que la métrica contaba como exportación cada intento
 *    fallido.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("@vercel/analytics", () => ({ track: vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import { track } from "@vercel/analytics";
import { toast } from "sonner";
import { buildExportUrl, descargarBlob, triggerDownload } from "@/lib/export";

const trackMock = vi.mocked(track);
const toastErrorMock = vi.mocked(toast.error);

/** Anclas creadas por el módulo, en orden. */
let anclas: HTMLAnchorElement[] = [];
/** Object URLs liberados, para comprobar que no se filtra el blob. */
let liberadas: string[] = [];

beforeEach(() => {
  trackMock.mockReset();
  toastErrorMock.mockReset();
  anclas = [];
  liberadas = [];

  // jsdom no implementa la Object URL API: sin esto no hay descarga que probar.
  URL.createObjectURL = () => `blob:mock/${anclas.length}`;
  URL.revokeObjectURL = (url: string) => {
    liberadas.push(url);
  };

  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    anclas.push(this);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** Respuesta de éxito con la cabecera que manda `download_export`. */
function respuestaOk(nombre: string, cuerpo = "col\n1\n"): Response {
  return new Response(cuerpo, {
    status: 200,
    headers: { "Content-Disposition": `attachment; filename="${nombre}"` },
  });
}

describe("buildExportUrl", () => {
  it("sets the format query param", () => {
    const url = buildExportUrl("/api/v1/exports/download", "csv", {});
    expect(url).toBe("/api/v1/exports/download?format=csv");
  });

  it("pide el Excel como `excel`, que es el literal que acepta la API", () => {
    // Regresión: con `xlsx` la API respondía 422 y la exportación a Excel no
    // funcionaba en ninguna pantalla de la consola.
    const url = buildExportUrl("/api/v1/exports/download", "excel", {});
    expect(new URLSearchParams(url.split("?")[1]).get("format")).toBe("excel");
    expect(url).not.toContain("xlsx");
  });

  it("includes non-empty filter params", () => {
    const url = buildExportUrl("/api/v1/exports/download", "csv", {
      q: "obras",
      estado: "PUB",
    });
    const params = new URLSearchParams(url.split("?")[1]);
    expect(params.get("format")).toBe("csv");
    expect(params.get("q")).toBe("obras");
    expect(params.get("estado")).toBe("PUB");
  });

  it("skips empty-string filter params", () => {
    const url = buildExportUrl("/api/v1/exports/download", "excel", {
      q: "obras",
      estado: "",
    });
    const params = new URLSearchParams(url.split("?")[1]);
    expect(params.has("estado")).toBe(false);
    expect(params.get("q")).toBe("obras");
  });

  it("merges extra params on top of filter params", () => {
    const url = buildExportUrl(
      "/api/v1/exports/download",
      "excel",
      { q: "obras" },
      { scope: "all" },
    );
    const params = new URLSearchParams(url.split("?")[1]);
    expect(params.get("format")).toBe("excel");
    expect(params.get("q")).toBe("obras");
    expect(params.get("scope")).toBe("all");
  });

  it("lets extraParams override a colliding filter param key", () => {
    const url = buildExportUrl(
      "/api/v1/exports/download",
      "csv",
      { scope: "filtered" },
      { scope: "all" },
    );
    const params = new URLSearchParams(url.split("?")[1]);
    expect(params.get("scope")).toBe("all");
  });

  it("uses the given endpoint", () => {
    const url = buildExportUrl("/api/v1/custom/endpoint", "csv", {});
    expect(url.startsWith("/api/v1/custom/endpoint?")).toBe(true);
  });
});

describe("triggerDownload", () => {
  it("pide la URL con la cookie de sesión y entrega el fichero", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(respuestaOk("licitaciones_20260828.csv"));
    vi.stubGlobal("fetch", fetchMock);

    await triggerDownload("/api/v1/exports/download?format=csv&q=obras");

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/exports/download?format=csv&q=obras", {
      credentials: "include",
    });
    expect(anclas).toHaveLength(1);
    expect(anclas[0].getAttribute("href")).toBe("blob:mock/0");
    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  it("respeta el nombre que anuncia el servidor y libera el object URL", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(respuestaOk("licitaciones_20260828.xlsx")),
    );

    await triggerDownload("/api/v1/exports/download?format=excel");

    // Con un blob el navegador ya no ve `Content-Disposition`: el nombre sale
    // del atributo `download` o el fichero se guarda con el UUID del blob.
    expect(anclas[0].getAttribute("download")).toBe("licitaciones_20260828.xlsx");
    expect(liberadas).toEqual(["blob:mock/0"]);
  });

  it("mide el Excel como `xlsx` aunque se pida como `excel`", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(respuestaOk("licitaciones_20260828.xlsx")),
    );

    await triggerDownload("/api/v1/exports/download?format=excel&q=SAP");

    expect(trackMock).toHaveBeenCalledTimes(1);
    expect(trackMock).toHaveBeenCalledWith("export_lanzado", {
      formato: "xlsx",
      recurso: "exports/download",
    });
  });

  it("no cuenta como exportación una respuesta de error, y avisa", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(new Response("", { status: 422 })),
    );

    await triggerDownload("/api/v1/exports/download?format=excel");

    expect(anclas).toHaveLength(0);
    expect(trackMock).not.toHaveBeenCalled();
    expect(toastErrorMock).toHaveBeenCalledTimes(1);
    expect(toastErrorMock.mock.calls[0][1]?.description).toContain("422");
  });

  it("dice que la sesión caducó ante un 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(new Response("", { status: 401 })),
    );

    await triggerDownload("/api/v1/exports/download?format=csv");

    expect(toastErrorMock.mock.calls[0][1]?.description).toContain("sesión");
    expect(trackMock).not.toHaveBeenCalled();
  });

  it("no propaga un fallo de red: avisa y no mide", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockRejectedValue(new TypeError("offline")));

    await expect(triggerDownload("/api/v1/exports/download?format=csv")).resolves.toBeUndefined();

    expect(anclas).toHaveLength(0);
    expect(trackMock).not.toHaveBeenCalled();
    expect(toastErrorMock).toHaveBeenCalledTimes(1);
  });
});

describe("descargarBlob", () => {
  it("entrega el fichero con el nombre pedido y libera el object URL", () => {
    descargarBlob("investigador_resultados_1.csv", new Blob(["a,b\n"]), "investigador");

    expect(anclas).toHaveLength(1);
    expect(anclas[0].getAttribute("download")).toBe("investigador_resultados_1.csv");
    expect(liberadas).toEqual(["blob:mock/0"]);
  });

  it("mide la descarga que se arma en el cliente, con su recurso", () => {
    // Estas tres pantallas no pasan por `/exports/download`, así que sin este
    // helper sus descargas no aparecían en la métrica de exportación.
    descargarBlob("adjudicaciones-empresa-42.csv", new Blob(["a\n"]), "adjudicaciones-empresa");

    expect(trackMock).toHaveBeenCalledWith("export_lanzado", {
      formato: "csv",
      recurso: "adjudicaciones-empresa",
    });
  });

  it("no manda el nombre del fichero: ahí puede ir un identificador", () => {
    descargarBlob("adjudicaciones-empresa-42.csv", new Blob(["a\n"]), "adjudicaciones-empresa");

    const propiedades = JSON.stringify(trackMock.mock.calls[0][1]);
    expect(propiedades).not.toContain("42");
  });

  it("marca como `otro` un formato que no sea CSV ni XLSX", () => {
    descargarBlob("informe.pdf", new Blob(["%PDF"]), "detalle");

    expect(trackMock).toHaveBeenCalledWith("export_lanzado", {
      formato: "otro",
      recurso: "detalle",
    });
  });
});
