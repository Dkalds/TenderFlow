import { describe, it, expect, vi, afterEach } from "vitest";
import { buildExportUrl, triggerDownload } from "@/lib/export";

describe("buildExportUrl", () => {
  it("sets the format query param", () => {
    const url = buildExportUrl("/api/v1/exports/download", "csv", {});
    expect(url).toBe("/api/v1/exports/download?format=csv");
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
    const url = buildExportUrl("/api/v1/exports/download", "xlsx", {
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
      "xlsx",
      { q: "obras" },
      { scope: "all" },
    );
    const params = new URLSearchParams(url.split("?")[1]);
    expect(params.get("format")).toBe("xlsx");
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
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("creates an anchor, clicks it and removes it", () => {
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    const appendSpy = vi.spyOn(document.body, "appendChild");
    const removeSpy = vi.spyOn(document.body, "removeChild");

    triggerDownload("/api/v1/exports/download?format=csv");

    expect(appendSpy).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(removeSpy).toHaveBeenCalledTimes(1);

    const anchor = appendSpy.mock.calls[0][0] as HTMLAnchorElement;
    expect(anchor.tagName).toBe("A");
    expect(anchor.getAttribute("href")).toBe("/api/v1/exports/download?format=csv");
    expect(anchor.getAttribute("download")).toBe("");
  });
});
