import { describe, expect, it } from "vitest";

import { urlHttp } from "@/lib/url-http";

describe("urlHttp", () => {
  it.each([
    "https://example.org/pcap.pdf",
    "http://example.org/pcap.pdf",
    "/docs/pcap.pdf",
    "/docs/pliego técnico.pdf",
  ])("devuelve %s tal cual", (url) => {
    expect(urlHttp(url)).toBe(url);
  });

  it.each([
    "javascript:alert(1)",
    "data:text/html;base64,AAAA",
    "ftp://example.org/x.pdf",
    "docs/pcap.pdf",
    "//example.org/x.pdf",
    "/\\example.org/x.pdf",
    "/docs/x\n.pdf",
    "/docs/x\t.pdf",
    "",
    null,
    undefined,
  ])("descarta %s", (url) => {
    expect(urlHttp(url)).toBeNull();
  });
});
