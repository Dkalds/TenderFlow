import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import NProgress from "nprogress";

vi.mock("next/navigation", () => ({
  usePathname: () => "/resumen",
  useSearchParams: () => new URLSearchParams(),
}));

import { RouteProgress } from "@/components/route-progress";

describe("RouteProgress", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("calls NProgress.done on mount (route settled)", () => {
    const done = vi.spyOn(NProgress, "done");
    render(<RouteProgress />);
    expect(done).toHaveBeenCalled();
  });

  it("starts NProgress when navigating to a different internal path", async () => {
    const start = vi.spyOn(NProgress, "start");
    render(<RouteProgress />);
    const a = document.createElement("a");
    a.href = `${window.location.origin}/otra-ruta`;
    document.body.appendChild(a);
    fireEvent.click(a);
    // NProgress.start() se difiere a un requestAnimationFrame para no bloquear
    // el hilo principal dentro del propio handler de click (evita INP largos).
    await new Promise((resolve) => requestAnimationFrame(resolve));
    expect(start).toHaveBeenCalled();
    document.body.removeChild(a);
  });

  it("does not start NProgress for same-path links", async () => {
    const start = vi.spyOn(NProgress, "start");
    render(<RouteProgress />);
    const a = document.createElement("a");
    a.href = `${window.location.origin}${window.location.pathname}`;
    document.body.appendChild(a);
    fireEvent.click(a);
    await new Promise((resolve) => requestAnimationFrame(resolve));
    expect(start).not.toHaveBeenCalled();
    document.body.removeChild(a);
  });
});
