import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";

function Boom(): React.ReactElement {
  throw new Error("chart blew up");
}

let shouldThrow = true;
function MaybeBoom(): React.ReactElement {
  if (shouldThrow) throw new Error("chart blew up");
  return <span>recovered</span>;
}

describe("ChartErrorBoundary", () => {
  beforeEach(() => {
    // React logs the caught error to console.error; silence it for a clean run.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders its children when there is no error", () => {
    render(
      <ChartErrorBoundary>
        <span>chart content</span>
      </ChartErrorBoundary>,
    );
    expect(screen.getByText("chart content")).toBeInTheDocument();
  });

  it("renders a fallback alert when a child throws", () => {
    render(
      <ChartErrorBoundary>
        <Boom />
      </ChartErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("resets error state when the retry button is clicked", () => {
    shouldThrow = true;
    render(
      <ChartErrorBoundary>
        <MaybeBoom />
      </ChartErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    // Once the underlying cause is gone, clicking retry re-renders the children.
    shouldThrow = false;
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("recovered")).toBeInTheDocument();
  });

  it("applies a custom className to the fallback container", () => {
    render(
      <ChartErrorBoundary className="custom-eb">
        <Boom />
      </ChartErrorBoundary>,
    );
    expect(screen.getByRole("alert").className).toContain("custom-eb");
  });
});
