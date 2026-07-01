import { describe, it, expect, vi, beforeEach } from "vitest";
import { getErrorMessage, notifyQueryError, notifyMutationError, notifyMutationSuccess } from "@/lib/query-feedback";
import { ApiError } from "@/lib/api-client";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

import { toast } from "sonner";

describe("getErrorMessage", () => {
  it("returns a server error message for ApiError 5xx", () => {
    const err = new ApiError(500, "Internal");
    expect(getErrorMessage(err)).toBe("Error del servidor. Inténtalo de nuevo en unos segundos.");
  });

  it("returns the error message for ApiError 4xx with message", () => {
    const err = new ApiError(404, "Not found");
    expect(getErrorMessage(err)).toBe("Not found");
  });

  it("returns fallback for ApiError 4xx without message", () => {
    const err = new ApiError(400, "");
    expect(getErrorMessage(err)).toBe("No se pudo completar la solicitud.");
  });

  it("returns 'Sin conexión' for Failed to fetch error", () => {
    const err = new Error("Failed to fetch");
    expect(getErrorMessage(err)).toBe("Sin conexión con el servidor.");
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
