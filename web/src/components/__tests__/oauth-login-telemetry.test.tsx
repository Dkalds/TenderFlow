import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";

vi.mock("@/lib/analytics", () => ({ registrarEvento: vi.fn() }));

import { OAuthLoginTelemetry } from "@/components/oauth-login-telemetry";
import { registrarEvento } from "@/lib/analytics";

describe("OAuthLoginTelemetry", () => {
  beforeEach(() => {
    vi.mocked(registrarEvento).mockClear();
    document.cookie = "oauth_login=; Max-Age=0; path=/";
  });

  it("registra Google una vez y consume la cookie efímera", async () => {
    document.cookie = "oauth_login=1; path=/";

    render(<OAuthLoginTelemetry />);

    await waitFor(() =>
      expect(registrarEvento).toHaveBeenCalledWith("sesion_iniciada", { metodo: "google" }),
    );
    expect(document.cookie).not.toContain("oauth_login=1");
  });

  it("no registra entradas normales", () => {
    render(<OAuthLoginTelemetry />);

    expect(registrarEvento).not.toHaveBeenCalled();
  });
});
