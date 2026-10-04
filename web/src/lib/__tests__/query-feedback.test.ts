import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  detalleTecnico,
  esErrorTransitorio,
  getErrorMessage,
  META_ERROR_EN_LINEA,
  notifyQueryError,
  notifyMutationError,
  notifyMutationSuccess,
  TIPO_CONSULTA_CANCELADA,
} from "@/lib/query-feedback";
import { ApiError } from "@/lib/api-client";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

import { toast } from "sonner";

describe("consulta cancelada por statement_timeout (503 query-timeout)", () => {
  const cancelada = () =>
    new ApiError(503, "La consulta tardó demasiado y se canceló. Acota los filtros.", TIPO_CONSULTA_CANCELADA);

  it("no se reintenta: se cortaría otra vez en el mismo punto", () => {
    expect(esErrorTransitorio(cancelada())).toBe(false);
  });

  it("un 503 sin ese tipo sigue siendo transitorio (arranque en frío)", () => {
    expect(esErrorTransitorio(new ApiError(503, "Service Unavailable"))).toBe(true);
  });

  it("enseña el detail de la API, que dice qué hacer", () => {
    expect(getErrorMessage(cancelada())).toBe("La consulta tardó demasiado y se canceló. Acota los filtros.");
  });
});

describe("getErrorMessage", () => {
  it("returns a server error message for ApiError 5xx", () => {
    const err = new ApiError(500, "Internal");
    expect(getErrorMessage(err)).toBe("Error del servidor. Vuelve a intentarlo en unos segundos.");
  });

  it("al leer, 403/404/422 se cuentan con el mensaje de su estado, no con el detail", () => {
    expect(getErrorMessage(new ApiError(403, "Acceso denegado. Scope insuficiente."))).toBe(
      "No tienes permiso para ver esto.",
    );
    expect(getErrorMessage(new ApiError(404, "Not Found"))).toBe("No existe o ya no está disponible.");
    expect(getErrorMessage(new ApiError(422, "La solicitud contiene datos inválidos."))).toBe(
      "Algún filtro no es válido; revísalo.",
    );
  });

  it("al actuar, el detail de la API explica qué falló de lo pedido", () => {
    const err = new ApiError(409, "Ya existe una regla con ese nombre.");
    expect(getErrorMessage(err, "accion")).toBe("Ya existe una regla con ese nombre.");
    expect(getErrorMessage(new ApiError(404, "Oportunidad no encontrada."), "accion")).toBe(
      "Oportunidad no encontrada.",
    );
  });

  it("otros 4xx enseñan el detail de la API", () => {
    expect(getErrorMessage(new ApiError(400, "El rango de fechas está invertido."))).toBe(
      "El rango de fechas está invertido.",
    );
  });

  it("returns fallback for ApiError 4xx without message", () => {
    const err = new ApiError(400, "");
    expect(getErrorMessage(err)).toBe("No se pudo completar la solicitud.");
  });

  it("un fallo de red, en cualquier motor, es «Sin conexión»", () => {
    for (const mensaje of ["Failed to fetch", "NetworkError when attempting to fetch resource.", "Load failed"]) {
      expect(getErrorMessage(new Error(mensaje))).toBe("Sin conexión. Vuelve a intentarlo.");
    }
  });

  it("returns the message for a generic Error", () => {
    expect(getErrorMessage(new Error("Something broke"))).toBe("Something broke");
  });

  it("returns fallback for unknown error types", () => {
    expect(getErrorMessage("string error")).toBe("Ocurrió un error inesperado.");
    expect(getErrorMessage(null)).toBe("Ocurrió un error inesperado.");
    expect(getErrorMessage(42)).toBe("Ocurrió un error inesperado.");
  });
});

describe("detalleTecnico", () => {
  it("un ApiError da estado, método y ruta, y el detail original si no es el visible", () => {
    const err = new ApiError(404, "Recurso no encontrado.", undefined, "GET /api/v1/empresas/8");
    expect(detalleTecnico(err)).toBe("404 · GET /api/v1/empresas/8 — Recurso no encontrado.");
  });

  it("no repite el mensaje que ya se enseña", () => {
    const err = new ApiError(400, "El rango de fechas está invertido.", undefined, "GET /api/v1/detalle");
    expect(detalleTecnico(err)).toBe("400 · GET /api/v1/detalle");
  });

  it("sin ruta, al menos el estado", () => {
    expect(detalleTecnico(new ApiError(500, "Internal"))).toBe("500 — Internal");
  });

  it("un fallo de red conserva el mensaje del navegador", () => {
    expect(detalleTecnico(new Error("Failed to fetch"))).toBe("Failed to fetch");
  });

  it("un Error cuyo mensaje ya es el visible no añade nada", () => {
    expect(detalleTecnico(new Error("backend caído"))).toBeUndefined();
    expect(detalleTecnico(null)).toBeUndefined();
  });

  it("si quien pinta enseña otro mensaje, el detail que no se ve va al detalle", () => {
    // Un 429 enseña por defecto su `detail`, y entonces el detalle no lo repite.
    // El asistente enseña el mensaje del estado: sin decir cuál es el visible,
    // el motivo de la API no saldría en ningún sitio.
    const err = new ApiError(429, "Presupuesto LLM daily global agotado.", undefined, "POST /api/v1/ask");
    expect(detalleTecnico(err)).toBe("429 · POST /api/v1/ask");
    expect(detalleTecnico(err, "Demasiadas peticiones seguidas. Espera unos segundos.")).toBe(
      "429 · POST /api/v1/ask — Presupuesto LLM daily global agotado.",
    );
    expect(detalleTecnico(new Error("boom"), "El asistente no pudo responder.")).toBe("boom");
  });
});

describe("META_ERROR_EN_LINEA", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("silencia el toast: el error ya se pinta en el panel", () => {
    notifyQueryError(new Error("oops"), META_ERROR_EN_LINEA);
    expect(toast.error).not.toHaveBeenCalled();
  });
});

describe("notifyQueryError", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls toast.error for a normal error", () => {
    notifyQueryError(new Error("oops"));
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("does NOT toast when meta.silent is true", () => {
    notifyQueryError(new Error("oops"), { silent: true });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("does NOT toast for a 401 auth error", () => {
    notifyQueryError(new ApiError(401, "Unauthorized"));
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("uses meta.errorTitle as the toast title", () => {
    notifyQueryError(new Error("x"), { errorTitle: "Custom title" });
    expect(toast.error).toHaveBeenCalledWith("Custom title", expect.any(Object));
  });

  it("falls back to default title when no meta.errorTitle", () => {
    notifyQueryError(new Error("x"));
    expect(toast.error).toHaveBeenCalledWith("Error al cargar datos", expect.any(Object));
  });
});

describe("notifyMutationError", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls toast.error for a mutation error", () => {
    notifyMutationError(new Error("fail"));
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("does NOT toast when meta.silent is true", () => {
    notifyMutationError(new Error("fail"), { silent: true });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("does NOT toast for a 401 auth error", () => {
    notifyMutationError(new ApiError(401, "Unauthorized"));
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("uses meta.errorTitle when provided", () => {
    notifyMutationError(new Error("x"), { errorTitle: "Mutation failed" });
    expect(toast.error).toHaveBeenCalledWith("Mutation failed", expect.any(Object));
  });

  it("falls back to default title", () => {
    notifyMutationError(new Error("x"));
    expect(toast.error).toHaveBeenCalledWith(
      "La acción no se pudo completar",
      expect.any(Object),
    );
  });
});

describe("notifyMutationSuccess", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls toast.success when successMessage is set", () => {
    notifyMutationSuccess({ successMessage: "Guardado!" });
    expect(toast.success).toHaveBeenCalledWith("Guardado!");
  });

  it("does NOT call toast.success when meta is undefined", () => {
    notifyMutationSuccess(undefined);
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("does NOT call toast.success when successMessage is absent", () => {
    notifyMutationSuccess({});
    expect(toast.success).not.toHaveBeenCalled();
  });
});
