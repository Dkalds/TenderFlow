import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { reportError } from "@/lib/report-error";

describe("reportError", () => {
  let consoleSpy: ReturnType<typeof vi.spyOn>;
  let debugSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  it("logs to console.error in development with an Error instance", () => {
    vi.stubEnv("NODE_ENV", "development");
    const err = new Error("test error");
    reportError("MyContext", err);
    expect(consoleSpy).toHaveBeenCalledWith("[MyContext]", "test error", "");
  });

  it("logs to console.error in development with a string error", () => {
    vi.stubEnv("NODE_ENV", "development");
    reportError("Ctx", "something went wrong");
    expect(consoleSpy).toHaveBeenCalledWith("[Ctx]", "something went wrong", "");
  });

  it("logs 'Unknown error' for non-string, non-Error values", () => {
    vi.stubEnv("NODE_ENV", "development");
    reportError("Ctx", 42);
    expect(consoleSpy).toHaveBeenCalledWith("[Ctx]", "Unknown error", "");
  });

  it("logs 'Unknown error' for object error values", () => {
    vi.stubEnv("NODE_ENV", "development");
    reportError("Ctx", { code: 500 });
    expect(consoleSpy).toHaveBeenCalledWith("[Ctx]", "Unknown error", "");
  });

  it("passes extra data to console.error", () => {
    vi.stubEnv("NODE_ENV", "development");
    reportError("Ctx", "msg", { userId: "123" });
    expect(consoleSpy).toHaveBeenCalledWith("[Ctx]", "msg", { userId: "123" });
  });

  it("logs stack trace to console.debug when error has a stack", () => {
    vi.stubEnv("NODE_ENV", "development");
    const err = new Error("stack test");
    reportError("Ctx", err);
    expect(debugSpy).toHaveBeenCalledWith(err.stack);
  });

  it("does not log stack when error has no stack", () => {
    vi.stubEnv("NODE_ENV", "development");
    const err = new Error("no stack");
    err.stack = undefined;
    reportError("Ctx", err);
    expect(debugSpy).not.toHaveBeenCalled();
  });

  it("does not call console.error outside of development", () => {
    // NODE_ENV is "test" by default in vitest
    reportError("Ctx", new Error("prod error"));
    expect(consoleSpy).not.toHaveBeenCalled();
  });

  it("still logs the stack in any env when error has a stack", () => {
    // debug runs regardless of NODE_ENV when error.stack is present
    const err = new Error("always debug");
    reportError("Ctx", err);
    expect(debugSpy).toHaveBeenCalledWith(err.stack);
  });
});
