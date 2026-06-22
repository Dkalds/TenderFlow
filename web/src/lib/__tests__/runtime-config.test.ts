import { afterEach, describe, expect, it, vi } from "vitest";

import { getGrafanaUrl } from "../runtime-config";

describe("getGrafanaUrl", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("returns null when the env var is not set", () => {
    vi.stubEnv("NEXT_PUBLIC_GRAFANA_URL", "");
    expect(getGrafanaUrl()).toBeNull();
  });

  it("returns the configured URL when set", () => {
    vi.stubEnv("NEXT_PUBLIC_GRAFANA_URL", "https://grafana.example.com");
    expect(getGrafanaUrl()).toBe("https://grafana.example.com");
  });

  it("treats whitespace-only as unset (no broken localhost link)", () => {
    vi.stubEnv("NEXT_PUBLIC_GRAFANA_URL", "   ");
    expect(getGrafanaUrl()).toBeNull();
  });
});
